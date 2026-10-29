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
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:
    sys.stderr.write('tkinter недоступен: %s\n' % exc)
    raise SystemExit(1)
APP_TITLE = 'OpenCode — менеджер провайдеров'
PACKAGES = ['@ai-sdk/openai-compatible', '@ai-sdk/openai', '@ai-sdk/anthropic', '@ai-sdk/google']

class _b:
    bg = '#010206'
    bg_panel = '#04101a'
    bg_panel_hi = '#071a26'
    bg_input = '#020a12'
    line = '#0e2b3a'
    cyan = '#6df4ff'
    cyan_soft = '#a6f0ff'
    cyan_dim = '#2b6a7a'
    amber = '#ffc16b'
    red = '#ff5568'
    green = '#6dffb0'
    ink = '#d9fbff'
    ink_dim = '#93c2d4'
    panel_fill = '#061722'
    panel_edge = '#1d5a6e'
    mono = ('Consolas', 10)
    mono_small = ('Consolas', 9)
    mono_title = ('Consolas', 12, 'bold')
    mono_big = ('Consolas', 18, 'bold')
    ui = ('Segoe UI', 10)

def _c(_Lb) -> None:
    _Lc = ttk.Style(_Lb)
    try:
        _Lc.theme_use('clam')
    except tk.TclError:
        pass
    _Lc.configure('.', background=_b.bg, foreground=_b.ink, fieldbackground=_b.bg_input, font=_b.ui, bordercolor=_b.line)
    _Lc.configure('TFrame', background=_b.bg)
    _Lc.configure('TLabel', background=_b.bg, foreground=_b.ink, font=_b.ui)
    _Lc.configure('TButton', background=_b.bg_panel_hi, foreground=_b.cyan_soft, bordercolor=_b.cyan_dim, focuscolor=_b.cyan, font=_b.mono_small, padding=(10, 6))
    _Lc.map('TButton', background=[('active', '#0b2c3d'), ('disabled', _b.bg_panel)], foreground=[('disabled', _b.cyan_dim)])
    _Lc.configure('Accent.TButton', background='#0b3547', foreground=_b.cyan, bordercolor=_b.cyan, font=_b.mono_small, padding=(10, 6))
    _Lc.map('Accent.TButton', background=[('active', '#0f4a61')])
    _Lc.configure('Danger.TButton', background='#2a0d13', foreground=_b.red, bordercolor='#7a2230', font=_b.mono_small, padding=(10, 6))
    _Lc.map('Danger.TButton', background=[('active', '#3d121b')])
    _Lc.configure('TEntry', fieldbackground=_b.bg_input, foreground=_b.cyan_soft, insertcolor=_b.cyan, bordercolor=_b.cyan_dim, lightcolor=_b.line, darkcolor=_b.bg_input, padding=6, font=_b.mono)
    _Lc.map('TEntry', bordercolor=[('focus', _b.cyan)])
    _Lc.configure('TCombobox', fieldbackground=_b.bg_input, background=_b.bg_panel_hi, foreground=_b.cyan_soft, arrowcolor=_b.cyan, bordercolor=_b.cyan_dim, padding=4)
    _Lc.map('TCombobox', fieldbackground=[('readonly', _b.bg_input)], foreground=[('readonly', _b.cyan_soft)])
    _Lc.configure('Treeview', background=_b.bg_panel, fieldbackground=_b.bg_panel, foreground=_b.ink, rowheight=24, font=_b.mono_small, bordercolor=_b.line)
    _Lc.map('Treeview', background=[('selected', '#0b3547')], foreground=[('selected', _b.cyan)])
    _Lc.configure('Treeview.Heading', background=_b.bg_panel_hi, foreground=_b.ink_dim, font=_b.mono_small, relief='flat')
    _Lc.map('Treeview.Heading', background=[('active', '#0b2c3d')], foreground=[('active', _b.cyan)])
    _Lc.configure('TScrollbar', background=_b.bg_panel_hi, troughcolor=_b.bg, bordercolor=_b.bg, arrowcolor=_b.cyan_dim)
    _Lc.map('TScrollbar', background=[('active', _b.cyan_dim)])

class _d(tk.Canvas):

    def __init__(self, master, width=None, height=None, radius=14, fill=None, outline=None, thickness=1, bg=None, **kw):
        self.radius = int(radius)
        self.fill = fill or _b.bg_panel
        self.outline = outline or _b.line
        self.thickness = int(thickness)
        outer_bg = bg or (master.cget('bg') if hasattr(master, 'cget') else _b.bg)
        super().__init__(master, bg=outer_bg, highlightthickness=0, bd=0, width=width or 1, height=height or 1, **kw)
        self.configure(bg=outer_bg)
        self.inner = tk.Frame(self, bg=self.fill)
        self._win = self.create_window(0, 0, window=self.inner, anchor='nw')
        self.bind('<Configure>', self._redraw)

    def _round_rect(self, x1, y1, x2, y2, r, fill='', outline='', width=1, **kw):
        r = max(0, min(int(r), int((x2 - x1) / 2), int((y2 - y1) / 2)))
        ids = []
        if fill:
            ids.append(self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=''))
            ids.append(self.create_rectangle(x1, y1 + r, x1 + r, y2 - r, fill=fill, outline=''))
            ids.append(self.create_rectangle(x2 - r, y1 + r, x2, y2 - r, fill=fill, outline=''))
            ids.append(self.create_oval(x1, y1, x1 + 2 * r, y1 + 2 * r, fill=fill, outline=''))
            ids.append(self.create_oval(x2 - 2 * r, y1, x2, y1 + 2 * r, fill=fill, outline=''))
            ids.append(self.create_oval(x1, y2 - 2 * r, x1 + 2 * r, y2, fill=fill, outline=''))
            ids.append(self.create_oval(x2 - 2 * r, y2 - 2 * r, x2, y2, fill=fill, outline=''))
        if outline:
            w = max(1, int(width))
            ids.append(self.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=w))
            ids.append(self.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=w))
            ids.append(self.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=w))
            ids.append(self.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=w))
            for sx, sy, st in ((1, 1, 90), (0, 1, 0), (0, 0, 270), (1, 0, 180)):
                ids.append(self.create_arc(x1 if sx else x2 - 2 * r, y1 if sy else y2 - 2 * r, x1 + 2 * r if sx else x2, y1 + 2 * r if sy else y2, start=st, extent=90, style='arc', outline=outline, width=w))
        return ids

    def _redraw(self, event=None):
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        self.delete('bgshape')
        pad = max(1, self.thickness)
        ids = self._round_rect(pad, pad, w - pad, h - pad, self.radius, fill=self.fill, outline=self.outline, width=self.thickness)
        for i in ids:
            self.itemconfigure(i, tags='bgshape')
        self.tag_lower('bgshape')
        inset = self.thickness + 6
        self.coords(self._win, inset, inset)
        self.itemconfigure(self._win, width=max(1, w - inset * 2), height=max(1, h - inset * 2))

class _e(tk.Canvas):

    def __init__(self, master, height=2, color='#6df4ff', **kw):
        super().__init__(master, height=height, bg=_b.bg, highlightthickness=0, **kw)
        self._color = color
        self._h = height
        self.bind('<Configure>', lambda e: self._draw(e.width))

    def _draw(self, w):
        self.delete('all')
        h = self._h
        self.create_line(0, h // 2, w, h // 2, fill=_b.line)
        self.create_line(0, h // 2, max(0, w // 3), h // 2, fill=self._color)
_CTX_CACHE: dict = {}

def _f():
    _Ld = []
    _Le = os.environ.get('SSL_CERT_FILE')
    if _Le:
        _Ld.append(Path(_Le))
    try:
        import certifi
        _Ld.append(Path(certifi.where()))
    except Exception:
        pass
    _Lf = Path(sys.prefix) / 'Lib' / 'site-packages'
    _Ld += [_Lf / 'pip' / '_vendor' / 'certifi' / 'cacert.pem', Path('C:\\Program Files\\Git\\mingw64\\etc\\ssl\\certs\\ca-bundle.crt'), Path('C:\\Program Files\\Git\\usr\\ssl\\certs\\ca-bundle.crt'), Path('C:\\Program Files\\Common Files\\SSL\\cert.pem')]
    _Lg = []
    for _Lh in _Ld:
        try:
            if _Lh and _Lh.is_file() and (_Lh.stat().st_size > 4096):
                if str(_Lh).lower() not in [str(_Li).lower() for _Li in _Lg]:
                    _Lg.append(_Lh)
        except OSError:
            continue
    return _Lg

def _g(_Lj, _Lk):
    try:
        with socket.create_connection((_Lk, 443), timeout=8) as _Ll:
            with _Lj.wrap_socket(_Ll, server_hostname=_Lk):
                return True
    except ssl.SSLCertVerificationError:
        return False
    except Exception:
        return True

def _h(_Lm):
    _Lm = (_Lm or '').lower()
    if _Lm in _CTX_CACHE:
        return _CTX_CACHE[_Lm]
    _Ln = ssl.create_default_context()
    _Lo = _g(_Ln, _Lm)
    if not _Lo:
        for _Lp in _f():
            try:
                _Lq = ssl.create_default_context(cafile=str(_Lp))
            except Exception:
                continue
            if _g(_Lq, _Lm):
                _Ln, _Lo = (_Lq, True)
                break
    _CTX_CACHE[_Lm] = _Ln
    return _Ln

def _i() -> Path:
    _Lr = os.environ.get('XDG_CONFIG_HOME')
    _Ls = Path(_Lr) if _Lr else Path.home() / '.config'
    return _Ls / 'opencode' / 'opencode.json'

def _j(_Lt: str) -> str:
    _Lu, _Lv, _Lw, _Lx, _Ly = ([], 0, len(_Lt), False, False)
    while _Lv < _Lw:
        _Lz = _Lt[_Lv]
        _L0 = _Lt[_Lv + 1] if _Lv + 1 < _Lw else ''
        if _Lx:
            _Lu.append(_Lz)
            if _Ly:
                _Ly = False
            elif _Lz == '\\':
                _Ly = True
            elif _Lz == '"':
                _Lx = False
            _Lv += 1
            continue
        if _Lz == '"':
            _Lx = True
            _Lu.append(_Lz)
            _Lv += 1
            continue
        if _Lz == '/' and _L0 == '/':
            while _Lv < _Lw and _Lt[_Lv] not in '\r\n':
                _Lv += 1
            continue
        if _Lz == '/' and _L0 == '*':
            _Lv += 2
            while _Lv < _Lw - 1 and (not (_Lt[_Lv] == '*' and _Lt[_Lv + 1] == '/')):
                _Lv += 1
            _Lv += 2
            continue
        _Lu.append(_Lz)
        _Lv += 1
    return re.sub(',(\\s*[}\\]])', '\\1', ''.join(_Lu))

def _k(_L1: Path) -> dict:
    if not _L1.exists():
        return {}
    _L2 = _L1.read_text(encoding='utf-8-sig')
    try:
        _L3 = json.loads(_L2)
    except json.JSONDecodeError:
        _L3 = json.loads(_j(_L2))
    if not isinstance(_L3, dict):
        raise ValueError('Корень конфига должен быть объектом JSON')
    return _L3
HISTORY_LIMIT = 50

def _l(_L4: Path) -> Path:
    return _L4.parent / 'backups'

def _m(_L5: Path) -> list:
    _L6 = []
    _L7 = []
    if _L5.exists():
        _L7 += [_L9 for _L9 in _L5.parent.glob(_L5.name + '.bak-*') if _L9.is_file()]
    _L8 = _l(_L5)
    if _L8.is_dir():
        _L7 += [_L9 for _L9 in _L8.glob(_L5.name + '.*.bak') if _L9.is_file()]
    for _L9 in _L7:
        _Laa = {'path': _L9, 'name': _L9.name, 'time': None, 'valid': False, 'providers': [], 'model': '', '_mtime': 0}
        try:
            _Laa['time'] = datetime.fromtimestamp(_L9.stat().st_mtime)
            _Laa['_mtime'] = _L9.stat().st_mtime
        except OSError:
            pass
        try:
            _Lab = _k(_L9)
            _Laa['valid'] = True
            _Laa['providers'] = list((_Lab.get('providers') or {}).keys())
            _Laa['model'] = _z(_Lab)
        except Exception:
            pass
        _L6.append(_Laa)
    _L6.sort(key=lambda e: e['_mtime'], reverse=True)
    return _L6

def _n(_Lac: Path):
    if not _Lac.exists():
        return None
    _Lad = _l(_Lac)
    _Lad.mkdir(parents=True, exist_ok=True)
    _Lae = datetime.now()
    _Laf = _Lae.strftime('%Y%m%d-%H%M%S') + '-%03d' % (_Lae.microsecond // 1000)
    _Lag = _Lad / ('%s.%s.bak' % (_Lac.name, _Laf))
    shutil.copy2(_Lac, _Lag)
    return _Lag

def _o(_Lah: Path, _Lai: int=HISTORY_LIMIT) -> None:
    _Laj = []
    _Lak = _l(_Lah)
    if _Lak.is_dir():
        _Laj.append((_Lak, '*.bak'))
    _Laj.append((_Lah.parent, _Lah.name + '.bak-*'))
    for _Lal, _Lam in _Laj:
        _Lan = sorted((_Lap for _Lap in _Lal.glob(_Lam) if _Lap.is_file()), key=lambda p: _Lap.stat().st_mtime, reverse=True)
        for _Lao in _Lan[_Lai:]:
            try:
                _Lao.unlink()
            except OSError:
                pass

def _p(_Laq: Path, _Lar: dict):
    _Laq.parent.mkdir(parents=True, exist_ok=True)
    _Las = _n(_Laq)
    _Lat = _Laq.with_name(_Laq.name + '.tmp')
    _Lat.write_text(json.dumps(_Lar, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(_Lat, _Laq)
    _o(_Laq)
    return _Las

def _q(_Lau: Path, _Lav: Path):
    _Law = _k(_Lav)
    if not isinstance(_Law, dict):
        raise ValueError('Снимок не содержит объект JSON')
    _Lax = _n(_Lau)
    _Lay = _Lau.with_name(_Lau.name + '.tmp')
    _Lay.write_text(_Lav.read_text(encoding='utf-8-sig'), encoding='utf-8')
    os.replace(_Lay, _Lau)
    _o(_Lau)
    return _Lax

def _r(_Laz: str) -> str:
    _Laz = (_Laz or '').strip()
    if not _Laz:
        return _Laz
    if not re.match('^[a-z][a-z0-9+.-]*://', _Laz, re.I):
        _Laz = 'https://' + _Laz
    return _Laz.rstrip('/')

def _s(_La0: str, _La1: str='', _La2: float=15.0):
    _La3 = urllib.request.Request(_La0, method='GET')
    _La3.add_header('Accept', 'application/json')
    _La3.add_header('User-Agent', 'opencode-provider-manager/2.0')
    if _La1:
        _La3.add_header('Authorization', 'Bearer ' + _La1)
    _La4 = urllib.parse.urlsplit(_La0).hostname or ''
    try:
        with urllib.request.urlopen(_La3, timeout=_La2, context=_h(_La4)) as _La6:
            _La7 = _La6.read().decode('utf-8', 'replace')
            _La8 = _La6.status
    except urllib.error.HTTPError as _La5:
        _La7 = _La5.read().decode('utf-8', 'replace')
        _La8 = _La5.code
    try:
        return (_La8, json.loads(_La7))
    except Exception:
        return (_La8, _La7)

def _t(_La9, _Lba) -> dict:
    try:
        _La9 = float(_La9)
        _Lbc = float(_Lba)
    except Exception:
        return {}
    if not _Lbc or _Lbc <= 0:
        return {}
    _Lbb = _La9 / _Lbc
    return {'tokens_by_coef': int(_Lbb), 'text': _w(int(_Lbb))}

def _u(_Lbd: str, _Lbe: str) -> dict:
    _Lbf = _r(_Lbd)
    if not _Lbf:
        raise ValueError('Не задан URL провайдера')
    _Lbg = [_Lbf]
    if re.search('/v\\d+[a-z]?$', _Lbf, re.I):
        _Lbg.append(_Lbf[:_Lbf.rfind('/')])
    _Lbh = []
    for _Lbi in _Lbg:
        for _Lbj in ('/balance', '/credits', '/usage'):
            _Lbk = _Lbi + _Lbj
            try:
                _Lbn, _Lbo = _s(_Lbk, _Lbe)
            except Exception as _Lbl:
                _Lbh.append('%s: %s' % (_Lbk, _Lbl))
                continue
            if _Lbn == 404:
                continue
            if _Lbn in (401, 403):
                raise PermissionError('Сервер отклонил ключ (HTTP %s)' % _Lbn)
            if _Lbn >= 400:
                _Lbh.append('%s: HTTP %s' % (_Lbk, _Lbn))
                continue
            if not isinstance(_Lbo, dict):
                continue
            _Lbm = _v(_Lbo)
            if _Lbm:
                _Lbm['url'] = _Lbk
                _Lbm['raw'] = _Lbo
                return _Lbm
    raise RuntimeError('Эндпоинт баланса не найден. Проверено: %d адрес(ов). Последние ошибки: %s' % (len(_Lbh), '; '.join(_Lbh[-3:]) or '—'))

def _v(data: dict) -> dict:
    out = {'tokens': None, 'usd': None, 'text': ''}

    def as_int(_Les):
        try:
            if isinstance(_Les, bool) or _Les is None:
                return None
            return int(float(_Les))
        except Exception:
            return None

    def as_float(_Let):
        try:
            if isinstance(_Let, bool) or _Let is None:
                return None
            return float(_Let)
        except Exception:
            return None
    for k in ('token_balance', 'balance_tokens', 'tokens_left', 'tokens', 'credit_tokens'):
        v = as_int(data.get(k))
        if v is not None:
            out['tokens'] = v
            break
    for k in ('balance', 'remaining', 'credits', 'credit_balance', 'amount', 'usd'):
        v = as_float(data.get(k))
        if v is not None:
            out['usd'] = v
            break
    if out['usd'] is None:
        granted = as_float(data.get('total_granted'))
        used = as_float(data.get('total_used')) or as_float(data.get('total_usage'))
        if granted is not None:
            used = used or 0.0
            out['usd'] = (granted - used) / 100.0 if granted > 1000 else granted - used
    if out['tokens'] is None:
        total = as_int(data.get('total_available')) or as_int(data.get('remaining_tokens'))
        if total is not None:
            out['tokens'] = total
    parts = []
    if out['usd'] is not None:
        parts.append('%.2f' % out['usd'])
    if out['tokens'] is not None:
        parts.append(_w(out['tokens']))
    out['text'] = ' • '.join(parts) if parts else ''
    return out

def _w(_Lbp) -> str:
    try:
        _Lbp = int(_Lbp)
    except Exception:
        return str(_Lbp)
    if _Lbp >= 1000000000:
        return '%.2f млрд токенов' % (_Lbp / 1000000000)
    if _Lbp >= 1000000:
        return '%.2f млн токенов' % (_Lbp / 1000000)
    if _Lbp >= 1000:
        return '%.1f тыс. токенов' % (_Lbp / 1000)
    return '%d токенов' % _Lbp

def _x(_Lbq: str, _Lbr: str) -> list:
    _Lbs = _r(_Lbq)
    if not _Lbs:
        raise ValueError('Не задан URL провайдера')
    _Lbt = []
    if re.search('/v\\d+[a-z]?$', _Lbs, re.I):
        _Lbt.append(_Lbs + '/models')
    else:
        _Lbt += [_Lbs + '/v1/models', _Lbs + '/models']
    _Lbu = None
    for _Lbv in _Lbt:
        try:
            _Lb1, _Lb2 = _s(_Lbv, _Lbr)
        except Exception as _Lbw:
            _Lbu = _Lbw
            continue
        if _Lb1 == 404:
            continue
        if _Lb1 in (401, 403):
            raise PermissionError('Сервер отклонил ключ (HTTP %s)' % _Lb1)
        if _Lb1 >= 400:
            raise RuntimeError('HTTP %s при запросе %s' % (_Lb1, _Lbv))
        _Lbx = _Lb2.get('data') or _Lb2.get('models') or [] if isinstance(_Lb2, dict) else _Lb2
        _Lby = []
        for _Lbz in _Lbx or []:
            if isinstance(_Lbz, str):
                _Lbz = {'id': _Lbz}
            if not isinstance(_Lbz, dict):
                continue
            _Lb0 = _Lbz.get('id') or _Lbz.get('name')
            if not _Lb0:
                continue
            _Lby.append({'id': str(_Lb0), 'display': _Lbz.get('display_name') or _Lbz.get('name') or str(_Lb0), 'context': _Lbz.get('context_window') or _Lbz.get('contextWindow') or _Lbz.get('context_length') or _Lbz.get('max_context_tokens'), 'output': _Lbz.get('max_output_tokens') or _Lbz.get('max_tokens'), 'tools': _Lbz.get('supports_tools'), 'vision': _Lbz.get('supports_vision')})
        if _Lby:
            return sorted(_Lby, key=lambda m: m['display'].lower())
        _Lbu = RuntimeError('Сервер вернул пустой список моделей')
    if isinstance(_Lbu, Exception):
        raise _Lbu
    raise RuntimeError('Не удалось получить список моделей')

def _y(_Lb3: dict) -> list:
    _Lb4 = _Lb3.get('providers')
    _Lb5 = []
    if not isinstance(_Lb4, dict):
        return _Lb5
    for _Lb6, _Lb7 in _Lb4.items():
        _Lb7 = _Lb7 if isinstance(_Lb7, dict) else {}
        _Lb8 = _Lb7.get('settings') if isinstance(_Lb7.get('settings'), dict) else {}
        _Lb9 = _Lb7.get('models') if isinstance(_Lb7.get('models'), dict) else {}
        _Lcb, _Lcc = ([], [])
        for _Lca, _Lcd in _Lb9.items():
            _Lcc.append(_Lca)
            if isinstance(_Lcd, dict) and _Lcd.get('disabled'):
                continue
            _Lcb.append(_Lca)
        for _Lca in _Lcc:
            if _Lca not in _Lcb:
                continue
        _Lb5.append({'id': _Lb6, 'display_name': _Lb7.get('name') or _Lb6, 'coefficient': str(_Lb7.get('_coefficient') or ''), 'base_url': _Lb8.get('baseURL') or '', 'api_key': _Lb8.get('apiKey') or '', 'package': _Lb7.get('package') or PACKAGES[0], 'models': _Lcb, 'known_models': _Lcc, 'extra_settings': {_Lce: _Lcf for _Lce, _Lcf in _Lb8.items() if _Lce not in ('baseURL', 'apiKey')}, '_raw': copy.deepcopy(_Lb7)})
    return _Lb5

def _z(_Lcg: dict) -> str:
    _Lch = _Lcg.get('model')
    if isinstance(_Lch, str):
        return _Lch
    if isinstance(_Lch, dict):
        _Lci = _Lch.get('providerID') or ''
        _Lcj = _Lch.get('model') or _Lch.get('modelID') or ''
        if _Lci and _Lcj:
            return '%s/%s' % (_Lci, _Lcj)
    return ''

def _0(_Lck: str):
    _Lck = (_Lck or '').strip()
    if '/' not in _Lck:
        return ('', '')
    _Lcl, _Lcm = _Lck.split('/', 1)
    return (_Lcl.strip(), _Lcm.strip())

def _1(_Lcn: dict, _Lco=None) -> dict:
    _Lcp = copy.deepcopy(_Lco) if isinstance(_Lco, dict) else {}
    _Lcp.pop('disabled', None)
    _Lcp.setdefault('name', _Lcn.get('display') or _Lcn['id'])
    _Lcq = _Lcp.get('limit') if isinstance(_Lcp.get('limit'), dict) else {}
    if _Lcn.get('context'):
        _Lcq['context'] = int(_Lcn['context'])
    if _Lcn.get('output'):
        _Lcq['output'] = int(_Lcn['output'])
    if _Lcq:
        _Lcp['limit'] = _Lcq
    _Lcr = _Lcp.get('capabilities') if isinstance(_Lcp.get('capabilities'), dict) else {}
    if _Lcn.get('tools') is not None:
        _Lcr['tools'] = bool(_Lcn['tools'])
    _Lcr.setdefault('tools', True)
    if _Lcn.get('vision'):
        _Lcr['input'] = ['text', 'image']
    _Lcr.setdefault('input', ['text'])
    _Lcr.setdefault('output', ['text'])
    _Lcp['capabilities'] = _Lcr
    return _Lcp

def _2(_Lcs):
    if isinstance(_Lcs, dict):
        return {_Lcu: _2(_Lct) for _Lcu, _Lct in _Lcs.items() if not _Lcu.startswith('_')}
    if isinstance(_Lcs, list):
        return [_2(_Lct) for _Lct in _Lcs]
    return _Lcs

def _3(_Lcv: dict, _Lcw: str) -> str:
    _Lcx = _Lcv.get('providers') or {}
    _Lcy = _Lcx.get(_Lcw) or {}
    _Lcz = _Lcy.get('_coefficient')
    if _Lcz in (None, ''):
        return ''
    return str(_Lcz)

def _4(_Lc0: dict) -> dict:
    _Lc1 = {}
    _Lc2 = _r(_Lc0.get('base_url', ''))
    if _Lc2:
        _Lc1['baseURL'] = _Lc2
    if _Lc0.get('api_key'):
        _Lc1['apiKey'] = _Lc0['api_key']
    for _Lc8, _Lc9 in (_Lc0.get('extra_settings') or {}).items():
        _Lc1[_Lc8] = _Lc9
    _Lc3 = copy.deepcopy(_Lc0.get('_raw') or {})
    _Lc4 = str(_Lc0.get('coefficient') or '').strip()
    if _Lc4:
        _Lc3['_coefficient'] = _Lc4
    else:
        _Lc3.pop('_coefficient', None)
    _Lc3['name'] = _Lc0.get('display_name') or _Lc0.get('id')
    _Lc3['package'] = _Lc0.get('package') or PACKAGES[0]
    if _Lc1:
        _Lc3['settings'] = _Lc1
    else:
        _Lc3.pop('settings', None)
    _Lc5 = _Lc3.get('models') if isinstance(_Lc3.get('models'), dict) else {}
    _Lc6 = {}
    for _Lc7 in _Lc0.get('models') or []:
        _Lc6[_Lc7] = _1({'id': _Lc7}, _Lc5.get(_Lc7))
    for _Lc7, _Lda in _Lc5.items():
        if _Lc7 in _Lc6:
            continue
        _Ldb = copy.deepcopy(_Lda) if isinstance(_Lda, dict) else {}
        _Ldb['disabled'] = True
        _Lc6[_Lc7] = _Ldb
    if _Lc6:
        _Lc3['models'] = _Lc6
    else:
        _Lc3.pop('models', None)
    return _Lc3

def _5(_Ldc: dict, _Ldd: list) -> dict:
    _Lde = copy.deepcopy(_Ldc)
    if not isinstance(_Lde.get('providers'), dict):
        _Lde['providers'] = {}
    _Lde['providers'] = {_Ldh['id']: _4(_Ldh) for _Ldh in _Ldd}
    _Ldf = _z(_Lde)
    _Ldg = _0(_Ldf)[0]
    if _Ldf and _Ldg not in _Lde['providers']:
        _Lde.pop('model', None)
    return _Lde
EXPORT_TYPE = 'opencode-provider-profiles'
EXPORT_VERSION = 2
EXPORT_TYPE_SINGLE = 'opencode-provider-profile'

def _6(_Ldi: dict) -> dict:
    return {'id': _Ldi['id'], 'display_name': _Ldi['display_name'], 'coefficient': str(_Ldi.get('coefficient') or ''), 'base_url': _Ldi['base_url'], 'package': _Ldi['package'], 'api_key': _Ldi['api_key'], 'models': list(_Ldi['models']), 'known_models': list(_Ldi['known_models']), 'extra_settings': _Ldi.get('extra_settings') or {}, 'raw': _Ldi.get('_raw') or {}}

def _7(_Ldj: list, _Ldk: str='') -> dict:
    _Ldl = {'version': EXPORT_VERSION, 'type': EXPORT_TYPE, 'profiles': [_6(_Ldn) for _Ldn in _Ldj]}
    _Ldm = (_Ldk or '').strip()
    if _Ldm and _Ldm != '(не задана)':
        _Ldl['default_model'] = _Ldm
    return _Ldl

def _8(_Ldo: dict) -> dict:
    if not isinstance(_Ldo, dict):
        raise ValueError('запись профиля не является объектом JSON')
    _Ldp = str(_Ldo.get('id') or '').strip()
    if not re.match('^[A-Za-z0-9._-]+$', _Ldp or ''):
        raise ValueError('отсутствует корректный ID профиля')
    _Ldq = [str(_Lds) for _Lds in _Ldo.get('models') or [] if str(_Lds).strip()]
    _Ldr = [str(_Lds) for _Lds in _Ldo.get('known_models') or _Ldq if str(_Lds).strip()]
    return {'id': _Ldp, 'display_name': _Ldo.get('display_name') or _Ldp, 'coefficient': str(_Ldo.get('coefficient') or ''), 'base_url': _Ldo.get('base_url') or '', 'api_key': _Ldo.get('api_key') or '', 'package': _Ldo.get('package') or PACKAGES[0], 'models': _Ldq, 'known_models': _Ldr, 'extra_settings': _Ldo.get('extra_settings') or {}, '_raw': _Ldo.get('raw') or None}

def _9(_Ldt) -> tuple:
    if isinstance(_Ldt, list):
        _Ldy, _Ldz = (_Ldt, '')
    elif isinstance(_Ldt, dict):
        _Ldz = str(_Ldt.get('default_model') or '').strip()
        if isinstance(_Ldt.get('profiles'), list):
            _Ldy = _Ldt['profiles']
        elif _Ldt.get('id'):
            _Ldy = [_Ldt]
        else:
            raise ValueError('В файле нет профилей (ожидается ключ "profiles")')
    else:
        raise ValueError('Файл не содержит объект JSON')
    _Ldu = []
    for _Ldv, _Ldw in enumerate(_Ldy, 1):
        try:
            _Ldu.append(_8(_Ldw))
        except ValueError as _Ldx:
            raise ValueError('Профиль №%d: %s' % (_Ldv, _Ldx))
    if not _Ldu:
        raise ValueError('В файле нет ни одного профиля')
    return (_Ldu, _Ldz)

class _aa(tk.Toplevel):

    def __init__(self, app, profile):
        super().__init__(app.root)
        self.app = app
        self.is_new = profile is None
        self._original_id = (profile or {}).get('id', '')
        self.result = None
        self._results = queue.Queue()
        self.models = []
        self.model_vars = {}
        self.known_models = list((profile or {}).get('known_models', []))
        self._raw = (profile or {}).get('_raw')
        self.title('НОВЫЙ ПРОФИЛЬ' if self.is_new else 'ПРОФИЛЬ ' + str(profile['id']).upper())
        self.geometry('860x720')
        self.minsize(760, 470)
        self.configure(bg=_b.bg)
        self.transient(app.root)
        self.grab_set()
        self.var_id = tk.StringVar(master=self, value=(profile or {}).get('id', ''))
        self.var_name = tk.StringVar(master=self, value=(profile or {}).get('display_name', ''))
        self.var_url = tk.StringVar(master=self, value=(profile or {}).get('base_url', ''))
        self.var_key = tk.StringVar(master=self, value=(profile or {}).get('api_key', ''))
        self.var_pkg = tk.StringVar(master=self, value=(profile or {}).get('package', PACKAGES[0]))
        self.var_set_default = tk.BooleanVar(master=self, value=False)
        self.var_coef = tk.StringVar(master=self, value=str((profile or {}).get('coefficient', '') or ''))
        self.var_filter = tk.StringVar(master=self)
        self.var_filter.trace_add('write', lambda *a: self._render_models())
        self._balance_value = (profile or {}).get('_balance') or None
        self.var_coef.trace_add('write', lambda *a: self._update_estimate())
        self._build()
        if self._balance_value:
            try:
                self.lbl_balance.configure(text=self._balance_value.get('text') or '—', fg=_b.green)
                self.lbl_balance_src.configure(text=(self._balance_value.get('url') or '') + '  •  из последнего запроса')
            except Exception:
                pass
        try:
            app.clipboard.bind_tree(self)
        except Exception:
            pass
        try:
            self.after(60, self._focus_first_field)
        except Exception:
            pass
        self.bind('<Escape>', lambda e: self._cancel())
        if not self.is_new and self.known_models:
            for mid in self.known_models:
                self.models.append({'id': mid, 'display': mid})
            self._render_models()

    def _focus_first_field(self):
        try:
            self.e_id.focus_set()
        except Exception:
            pass

    def _field(self, parent, row, label, var, show=None):
        tk.Label(parent, text=label, bg=_b.bg, fg=_b.cyan_soft, font=_b.mono_small, width=15, anchor='w').grid(row=row, column=0, sticky='w', padx=(4, 8), pady=4)
        ent = ttk.Entry(parent, textvariable=var, font=_b.mono)
        if show:
            ent.configure(show=show)
        ent.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        return ent

    def _build(self):
        head = tk.Frame(self, bg=_b.bg)
        head.pack(fill='x', padx=16, pady=(14, 2))
        tk.Label(head, text='ПРОФИЛЬ ПРОВАЙДЕРА', bg=_b.bg, fg=_b.cyan, font=_b.mono_title).pack(anchor='w')
        _e(self, color=_b.cyan).pack(fill='x', padx=16, pady=(4, 8))
        form = tk.Frame(self, bg=_b.bg)
        form.pack(fill='x', padx=16)
        self.e_id = self._field(form, 0, 'ID ПРОВАЙДЕРА', self.var_id)
        self._field(form, 1, 'НАЗВАНИЕ', self.var_name)
        self._field(form, 2, 'URL ПРОВАЙДЕРА', self.var_url)
        self.e_key = self._field(form, 3, 'API KEY', self.var_key, show='•')
        ttk.Button(form, text='ПОКАЗАТЬ', command=self._toggle_key).grid(row=3, column=2, padx=6)
        tk.Label(form, text='ТРАНСПОРТ', bg=_b.bg, fg=_b.cyan_soft, font=_b.mono_small, width=15, anchor='w').grid(row=4, column=0, sticky='w', padx=(4, 8), pady=4)
        ttk.Combobox(form, values=PACKAGES, textvariable=self.var_pkg, state='readonly', font=_b.mono, width=34).grid(row=4, column=1, sticky='w', padx=6, pady=4)
        tk.Label(form, text='КОЭФФИЦИЕНТ', bg=_b.bg, fg=_b.cyan_soft, font=_b.mono_small, width=15, anchor='w').grid(row=5, column=0, sticky='w', padx=(4, 8), pady=4)
        coef_row = tk.Frame(form, bg=_b.bg)
        coef_row.grid(row=5, column=1, sticky='w', padx=6, pady=4)
        ttk.Entry(coef_row, textvariable=self.var_coef, font=_b.mono, width=10).pack(side='left')
        tk.Label(coef_row, text='напр. 0.1 — множитель тарифа (лимит ÷ коэффициент = запас токенов)', bg=_b.bg, fg=_b.ink_dim, font=_b.mono_small).pack(side='left', padx=8)
        form.columnconfigure(1, weight=1)
        row = tk.Frame(self, bg=_b.bg)
        row.pack(fill='x', padx=16, pady=(10, 4))
        self.btn_check = ttk.Button(row, text='ПОЛУЧИТЬ СПИСОК МОДЕЛЕЙ', style='Accent.TButton', command=self._check_key)
        self.btn_check.pack(side='left', padx=(4, 6), pady=4)
        self.btn_balance = ttk.Button(row, text='ЗАПРОСИТЬ БАЛАНС', command=self._check_balance)
        self.btn_balance.pack(side='left', padx=(0, 10), pady=4)
        self.lbl_status = tk.Label(row, text='ВВЕДИТЕ URL И КЛЮЧ, ЗАТЕМ ЗАПРОСИТЕ МОДЕЛИ', bg=_b.bg, fg=_b.cyan_soft, font=_b.mono_small)
        self.lbl_status.pack(side='left', padx=4)
        bal_row = tk.Frame(self, bg=_b.bg)
        bal_row.pack(fill='x', padx=16, pady=(0, 4))
        tk.Label(bal_row, text='БАЛАНС', bg=_b.bg, fg=_b.ink_dim, font=_b.mono_small).pack(side='left', padx=(6, 10))
        self.lbl_balance = tk.Label(bal_row, text='—', bg=_b.bg, fg=_b.amber, font=_b.mono_big if hasattr(_b, 'mono_big') else _b.mono_title)
        self.lbl_balance.pack(side='left', padx=4)
        self.lbl_balance_src = tk.Label(bal_row, text='', bg=_b.bg, fg=_b.cyan_dim, font=_b.mono_small)
        self.lbl_balance_src.pack(side='left', padx=10)
        self.lbl_balance_est = tk.Label(self, text='', bg=_b.bg, fg=_b.cyan_soft, font=_b.mono_small, anchor='w')
        self.lbl_balance_est.pack(fill='x', padx=18, pady=(0, 2))
        _e(self, color=_b.amber).pack(fill='x', padx=16, pady=(6, 6))
        mid = tk.Frame(self, bg=_b.bg)
        mid.pack(side='bottom', fill='both', expand=True, padx=16)
        mid.pack_propagate(False)
        mhead = tk.Frame(mid, bg=_b.bg)
        mhead.pack(fill='x')
        tk.Label(mhead, text='ДОСТУПНЫЕ МОДЕЛИ', bg=_b.bg, fg=_b.cyan, font=_b.mono_title).pack(side='left', padx=2)
        ttk.Button(mhead, text='☑ ВСЕ', width=8, style='Accent.TButton', command=lambda: self._set_all(True)).pack(side='right', padx=3)
        ttk.Button(mhead, text='☐ НИЧЕГО', width=10, style='Accent.TButton', command=lambda: self._set_all(False)).pack(side='right', padx=3)
        self.lbl_selected = tk.Label(mhead, text='ОТМЕЧЕНО: 0 / 0', bg=_b.bg, fg=_b.amber, font=_b.mono_small)
        self.lbl_selected.pack(side='right', padx=10)
        khint = tk.Frame(mid, bg=_b.bg)
        khint.pack(fill='x', pady=(2, 0))
        tk.Label(khint, text='SHIFT+КЛИК — ИНВЕРСИЯ   •   CTRL+КЛИК — ВКЛ/ВЫКЛ ВСЁ', bg=_b.bg, fg=_b.cyan_soft, font=_b.mono_small).pack(anchor='w', padx=2)
        srow = tk.Frame(mid, bg=_b.bg)
        srow.pack(fill='x', pady=(6, 4))
        tk.Label(srow, text='ФИЛЬТР', bg=_b.bg, fg=_b.ink_dim, font=_b.mono_small).pack(side='left', padx=(2, 8))
        ttk.Entry(srow, textvariable=self.var_filter, font=_b.mono).pack(side='left', fill='x', expand=True, padx=(0, 4))
        box_panel = _d(mid, radius=16, fill=_b.bg_panel, outline=_b.cyan_dim, thickness=1, bg=_b.bg)
        box_panel.pack(side='bottom', fill='both', expand=True, pady=(0, 6))
        box = box_panel.inner
        self.canvas = tk.Canvas(box, bg=_b.bg_panel, highlightthickness=0)
        sb = ttk.Scrollbar(box, orient='vertical', command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=_b.bg_panel)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.configure(yscrollcommand=sb.set)
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))
        self.canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.canvas.bind('<Enter>', self._bind_wheel)
        self.canvas.bind('<Leave>', self._unbind_wheel)
        bottom = tk.Frame(self, bg=_b.bg)
        bottom.pack(side='bottom', fill='x', padx=16, pady=(4, 14))
        tk.Checkbutton(bottom, text='МОДЕЛЬ ПО УМОЛЧАНИЮ', variable=self.var_set_default, bg=_b.bg, fg=_b.ink, selectcolor=_b.bg_input, activebackground=_b.bg, activeforeground=_b.cyan, font=_b.mono_small, bd=0).pack(side='left', padx=4)
        ttk.Button(bottom, text='ОТМЕНА', command=self._cancel).pack(side='right', padx=4)
        ttk.Button(bottom, text='СОХРАНИТЬ', style='Accent.TButton', command=self._save).pack(side='right', padx=4)

    def _bind_wheel(self, _=None):
        self.canvas.bind_all('<MouseWheel>', self._on_wheel)

    def _unbind_wheel(self, _=None):
        try:
            self.canvas.unbind_all('<MouseWheel>')
        except Exception:
            pass

    def _on_wheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        except Exception:
            pass

    def _toggle_key(self):
        showing = self.e_key.cget('show') == ''
        self.e_key.configure(show='•' if showing else '')

    def _set_all(self, value):
        for mid, var in self.model_vars.items():
            if self._visible(mid):
                var.set(value)
        self._update_counter()

    def toggle_all(self, flip=False, want=None):
        visible = [mid for mid in self.model_vars if self._visible(mid)]
        if not visible:
            return
        if flip:
            for mid in visible:
                self.model_vars[mid].set(not self.model_vars[mid].get())
        else:
            if want is None:
                want = not all((self.model_vars[mid].get() for mid in visible))
            for mid in visible:
                self.model_vars[mid].set(want)
        self._update_counter()

    def _count_selected(self):
        return sum((1 for v in self.model_vars.values() if v.get()))

    def _update_counter(self):
        try:
            self.lbl_selected.configure(text='ОТМЕЧЕНО: %d / %d' % (self._count_selected(), len(self.model_vars)))
        except Exception:
            pass

    def _visible(self, mid):
        q = (self.var_filter.get() or '').strip().lower()
        return not q or q in mid.lower() or q in self._display_for(mid).lower()

    def _display_for(self, mid):
        for m in self.models:
            if m['id'] == mid:
                return m.get('display') or mid
        return mid

    def _render_models(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self._update_counter()
        if not self.models:
            tk.Label(self.inner, text='МОДЕЛЕЙ ПОКА НЕТ — ПРОВЕРЬТЕ URL/КЛЮЧ', bg=_b.bg_panel, fg=_b.ink_dim, font=_b.mono_small).pack(anchor='w', padx=10, pady=10)
            return
        shown = 0
        for m in self.models:
            mid = m['id']
            if mid not in self.model_vars:
                var = tk.BooleanVar(value=mid in (self.known_models or []))
                var.trace_add('write', lambda *a: self._update_counter())
                self.model_vars[mid] = var
            if not self._visible(mid):
                continue
            shown += 1
            text = self._display_for(mid)
            if text != mid:
                text = '%s   (%s)' % (text, mid)
            cb = _ad(self.inner, self, self.model_vars[mid], text)
            cb.var = self.model_vars[mid]
            cb.pack(anchor='w', padx=8, pady=1, fill='x')
        if shown == 0:
            tk.Label(self.inner, text='ПО ФИЛЬТРУ НИЧЕГО НЕ НАЙДЕНО', bg=_b.bg_panel, fg=_b.ink_dim, font=_b.mono_small).pack(anchor='w', padx=10, pady=10)

    def _check_key(self):
        base, key = (self.var_url.get(), self.var_key.get())
        if not base.strip():
            messagebox.showwarning('Проверка', 'Сначала введите URL провайдера', parent=self)
            return
        self.btn_check.configure(state='disabled')
        self.lbl_status.configure(text='ПРОВЕРЯЕМ…')

        def work():
            try:
                self._results.put((_x(base, key), None))
            except Exception as _Lie:
                self._results.put((None, _Lie))
        threading.Thread(target=work, daemon=True).start()
        self._poll_results()

    def _poll_results(self):
        try:
            item = self._results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_results)
            return
        if isinstance(item, tuple) and len(item) == 3 and (item[0] == 'balance'):
            self._on_balance(item[1], item[2])
            return
        found, err = item
        self._on_checked(found, err)

    def _on_checked(self, found, err):
        self.btn_check.configure(state='normal')
        if err is not None:
            self.lbl_status.configure(text='ОШИБКА: %s' % err)
            messagebox.showerror('Проверка ключа', str(err), parent=self)
            return
        keep = {mid for mid, var in self.model_vars.items() if var.get()} or set(self.known_models or [])
        default_all = not keep
        self.models = found
        self.model_vars = {}
        for m in found:
            var = tk.BooleanVar(value=default_all or m['id'] in keep)
            var.trace_add('write', lambda *a: self._update_counter())
            self.model_vars[m['id']] = var
        self.lbl_status.configure(text='НАЙДЕНО МОДЕЛЕЙ: %d' % len(found))
        self._render_models()
        self._update_counter()

    def _check_balance(self):
        base, key = (self.var_url.get(), self.var_key.get())
        if not base.strip():
            messagebox.showwarning('Баланс', 'Сначала введите URL провайдера', parent=self)
            return
        self.btn_balance.configure(state='disabled')
        self.lbl_balance.configure(text='…', fg=_b.ink_dim)
        self.lbl_balance_src.configure(text='запрашиваю')

        def work():
            try:
                self._results.put(('balance', _u(base, key), None))
            except Exception as _Lif:
                self._results.put(('balance', None, _Lif))
        threading.Thread(target=work, daemon=True).start()
        self._poll_results()

    def _on_balance(self, data, err):
        try:
            self.btn_balance.configure(state='normal')
        except Exception:
            pass
        if err is not None:
            self.lbl_balance.configure(text='—', fg=_b.red)
            self.lbl_balance_src.configure(text=str(err)[:90])
            return
        text = data.get('text') or '—'
        self.lbl_balance.configure(text=text, fg=_b.green)
        self.lbl_balance_src.configure(text=data.get('url') or '')
        self._balance_value = data
        self._update_estimate()

    def _update_estimate(self):
        lbl = getattr(self, 'lbl_balance_est', None)
        if lbl is None:
            return
        try:
            coef_txt = (self.var_coef.get() or '').replace(',', '.').strip()
            data = self._balance_value
            if not data or not coef_txt:
                lbl.configure(text='')
                return
            units = data.get('tokens')
            if units is None:
                lbl.configure(text='')
                return
            est = _t(units, coef_txt)
            if not est:
                lbl.configure(text='коэффициент должен быть > 0')
                return
            lbl.configure(text='≈ %s по коэффициенту %s   (единиц на ключе: %s)' % (est['text'], coef_txt, format(units, ',').replace(',', ' ')))
        except Exception:
            pass

    def _save(self):
        pid = (self.var_id.get() or '').strip()
        if not pid:
            messagebox.showwarning('Проверка', 'Укажите ID провайдера', parent=self)
            return
        if not re.match('^[A-Za-z0-9._-]+$', pid):
            messagebox.showwarning('Проверка', 'ID может содержать только латиницу, цифры, «.», «_», «-»', parent=self)
            return
        base = _r(self.var_url.get())
        if not base:
            messagebox.showwarning('Проверка', 'Укажите URL провайдера', parent=self)
            return
        if not self.var_key.get().strip():
            if not messagebox.askyesno('API key', 'Ключ не заполнен. Сохранить без ключа?', parent=self):
                return
        others = [p['id'] for p in self.app.profiles if p['id'] != self._original_id]
        if pid in others:
            messagebox.showwarning('Проверка', 'Провайдер с таким ID уже существует', parent=self)
            return
        chosen = [mid for mid, var in self.model_vars.items() if var.get()]
        if not chosen and (not messagebox.askyesno('Модели', 'Ни одна модель не отмечена — профиль будет без моделей. Продолжить?', parent=self)):
            return
        self.result = {'id': pid, 'display_name': (self.var_name.get() or pid).strip(), 'base_url': base, 'api_key': self.var_key.get().strip(), 'package': self.var_pkg.get(), 'models': chosen, 'known_models': [m['id'] for m in self.models] or list(self.known_models), 'set_default': bool(self.var_set_default.get()), 'coefficient': self.var_coef.get().strip(), '_raw': copy.deepcopy(self._raw) if self._raw else None}
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

class _ab(tk.Toplevel):

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title('ИСТОРИЯ КОНФИГА И ОТКАТ')
        self.geometry('920x620')
        self.minsize(780, 430)
        self.configure(bg=_b.bg)
        self.transient(app.root)
        self.grab_set()
        head = tk.Frame(self, bg=_b.bg)
        head.pack(fill='x', padx=16, pady=(14, 2))
        tk.Label(head, text='ИСТОРИЯ ВЕРСИЙ', bg=_b.bg, fg=_b.cyan, font=_b.mono_title).pack(side='left', padx=2)
        ttk.Button(head, text='СНИМОК СЕЙЧАС', command=self.make_now).pack(side='right', padx=4)
        ttk.Button(head, text='ОБНОВИТЬ', command=self.reload).pack(side='right', padx=4)
        _e(self, color=_b.cyan).pack(fill='x', padx=16, pady=(4, 8))
        foot = tk.Frame(self, bg=_b.bg)
        foot.pack(side='bottom', fill='x', padx=16, pady=(4, 14))
        tk.Label(foot, text='ОТКАТ ВОССТАНАВЛИВАЕТ ФАЙЛ ЦЕЛИКОМ', bg=_b.bg, fg=_b.ink_dim, font=_b.mono_small).pack(side='left', padx=4)
        ttk.Button(foot, text='ЗАКРЫТЬ', command=self.destroy).pack(side='right', padx=4)
        ttk.Button(foot, text='ВОССТАНОВИТЬ ВЫБРАННОЕ', style='Accent.TButton', command=self.restore_selected).pack(side='right', padx=4)
        prev = tk.Frame(self, bg=_b.bg)
        prev.pack(side='bottom', fill='x', padx=16, pady=(8, 4))
        tk.Label(prev, text='СОДЕРЖИМОЕ СНИМКА', bg=_b.bg, fg=_b.ink_dim, font=_b.mono_small).pack(anchor='w')
        self.preview_box = tk.Text(prev, height=7, bg=_b.bg_input, fg=_b.ink, relief='flat', font=_b.mono_small, insertbackground=_b.cyan, wrap='none', highlightthickness=1, highlightbackground=_b.line)
        self.preview_box.pack(fill='both', expand=True, pady=4)
        mid_panel = _d(self, radius=18, fill=_b.bg_panel, outline=_b.cyan_dim, thickness=1, bg=_b.bg)
        mid_panel.pack(fill='both', expand=True, padx=16)
        mid = mid_panel.inner
        cols = ('time', 'name', 'providers', 'model')
        self.tree = ttk.Treeview(mid, columns=cols, show='headings', selectmode='browse')
        for col, title, width in (('time', 'КОГДА', 150), ('name', 'ФАЙЛ', 250), ('providers', 'ПРОВАЙДЕРЫ', 240), ('model', 'МОДЕЛЬ', 190)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor='w')
        vsb = ttk.Scrollbar(mid, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.preview())
        self.tree.bind('<Double-1>', lambda e: self.restore_selected())
        self.items = []
        try:
            self.app.clipboard.bind_tree(self)
        except Exception:
            pass
        self.reload()

    def reload(self):
        self.items = _m(self.app.config_path)
        self.tree.delete(*self.tree.get_children())
        for i, e in enumerate(self.items):
            when = e['time'].strftime('%d.%m.%Y %H:%M:%S') if e.get('time') else '?'
            provs = ', '.join(e.get('providers') or []) or '(нет данных)'
            self.tree.insert('', 'end', iid=str(i), values=(when, e['name'], provs, e.get('model') or '(не задана)'))
        if self.items:
            self.tree.selection_set('0')
            self.preview()
        else:
            self._set_preview('Снимков пока нет. Нажмите «СНИМОК СЕЙЧАС».')

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
            self.preview_box.configure(state='normal')
            self.preview_box.delete('1.0', 'end')
            self.preview_box.insert('1.0', text)
        except Exception:
            pass

    def preview(self):
        entry = self._selected()
        if not entry:
            return
        try:
            raw = entry['path'].read_text(encoding='utf-8-sig', errors='replace')
        except Exception as exc:
            self._set_preview('Не удалось прочитать снимок: %s' % exc)
            return
        self._set_preview(raw[:20000])

    def make_now(self):
        snap = self.app.snapshot_now('Ручной снимок')
        self.reload()
        if snap:
            messagebox.showinfo('Снимок', 'Сохранён:\n%s' % snap.name, parent=self)

    def restore_selected(self):
        entry = self._selected()
        if not entry:
            messagebox.showinfo('Откат', 'Выберите снимок в списке', parent=self)
            return
        self.app.quick_restore(entry)
        self.reload()

class _ac:
    pass

class _ad(tk.Checkbutton):

    def __init__(self, master, owner, variable, text, **kw):
        kw.setdefault('bg', _b.bg_panel)
        kw.setdefault('fg', _b.ink)
        kw.setdefault('selectcolor', _b.bg_input)
        kw.setdefault('activebackground', _b.bg_panel)
        kw.setdefault('activeforeground', _b.cyan)
        kw.setdefault('font', _b.mono_small)
        kw.setdefault('anchor', 'w')
        kw.setdefault('bd', 0)
        kw.setdefault('highlightthickness', 0)
        super().__init__(master, text=text, variable=variable, **kw)
        self._owner = owner
        self._watcher = variable
        self._old = variable.get()
        variable.trace_add('write', self._on_var)
        self.bind('<Button-1>', self._on_click, add='+')

    def _on_var(self, *_):
        self._old = self._watcher.get()

    def _on_click(self, event):
        mods = event.state
        shift = bool(mods & 1)
        ctrl = bool(mods & 4)
        ctrl2 = bool(mods & 8)
        alt = bool(mods & 131072)
        if shift or ctrl or ctrl2:
            if shift:
                self._owner.toggle_all(flip=True)
            else:
                self._owner.toggle_all(flip=False, want=not self._old)
            try:
                self.selection_clear()
            except Exception:
                pass
            return 'break'
        return None
VK_INSERT = 45
VK_A = 65
VK_C = 67
VK_V = 86
VK_X = 88
CONTROL_STATE = 4
SHORTCUT_EVENTS = {'paste': '<<Paste>>', 'copy': '<<Copy>>', 'cut': '<<Cut>>', 'select_all': '<<SelectAll>>'}
CONTROL_KEYCODES = {'paste': (VK_V,), 'copy': (VK_C, VK_INSERT), 'cut': (VK_X,), 'select_all': (VK_A,)}
LATIN_SHORTCUT_KEYSYMS = {'paste': ('v', 'V'), 'copy': ('c', 'C'), 'cut': ('x', 'X'), 'select_all': ('a', 'A')}
INPUT_CLASSES = ('TEntry', 'TCombobox', 'TSpinbox', 'Entry', 'Spinbox', 'Text')

def _ae(_Ld0):
    try:
        return _Ld0.winfo_class() in INPUT_CLASSES
    except Exception:
        return False

def _af(_Ld1, _Ld2):
    try:
        return int(getattr(_Ld1, _Ld2, 0) or 0)
    except Exception:
        return 0

def _ag(_Ld3):
    return _af(_Ld3, 'state')

def _ah(_Ld4):
    return _af(_Ld4, 'keycode')

def _ai(_Ld5):
    return str(getattr(_Ld5, 'keysym', '') or '')

def _aj(_Ld6):
    if _Ld6 is None:
        return None
    if not _ag(_Ld6) & CONTROL_STATE:
        return None
    _Ld7 = _ah(_Ld6)
    for _Ld8, _Ld9 in CONTROL_KEYCODES.items():
        if _Ld7 in _Ld9:
            return _Ld8
    return None

class _ak:

    def __init__(self, _Leu):
        self.root = _Leu
        self.menu = tk.Menu(_Leu, tearoff=0, bg=_b.bg_panel_hi, fg=_b.ink, activebackground='#0b3547', activeforeground=_b.cyan, font=_b.mono_small, bd=0, relief='flat')
        self.menu.add_command(label='ВЫРЕЗАТЬ        Ctrl+X', command=self._cut)
        self.menu.add_command(label='КОПИРОВАТЬ      Ctrl+C', command=self._copy)
        self.menu.add_command(label='ВСТАВИТЬ        Ctrl+V', command=self._paste)
        self.menu.add_separator()
        self.menu.add_command(label='ВЫДЕЛИТЬ ВСЁ    Ctrl+A', command=self._select_all)
        self._target = None
        self.menu.bind('<FocusOut>', lambda e: self.menu.unpost())

    def _widget(self, _Lev):
        _Lew = _Lev.widget
        return _Lew if _ae(_Lew) else None

    def bind(self, _Lex):
        _Lex.bind('<Button-3>', self.popup, add='+')
        return _Lex

    def bind_tree(self, _Ley):
        self.bind(_Ley)
        if _ae(_Ley):
            _Ley.bind('<Control-KeyPress>', self.on_control_key, add='+')
        for _Lez in _Ley.winfo_children():
            self.bind_tree(_Lez)

    def _target_for(self, _Le0=None):
        _Le1 = getattr(_Le0, 'widget', None) if _Le0 is not None else None
        if _ae(_Le1):
            return _Le1
        try:
            _Le1 = self.root.focus_get()
        except Exception:
            _Le1 = None
        return _Le1 if _ae(_Le1) else None

    def _run_shortcut(self, _Le2, _Le3):
        _Le4 = SHORTCUT_EVENTS[_Le3]
        if _Le2 is None:
            return None
        try:
            _Le2.event_generate(_Le4)
        except Exception:
            return None
        return 'break'

    def on_control_key(self, _Le5):
        _Le6 = _aj(_Le5)
        if _Le6 is None:
            return None
        if _ai(_Le5) in LATIN_SHORTCUT_KEYSYMS[_Le6]:
            return None
        return self._run_shortcut(self._target_for(_Le5), _Le6)

    def _cls(self, _Le7):
        try:
            return _Le7.winfo_class()
        except Exception:
            return ''

    def _copy(self):
        _Le8 = self._target
        if not _Le8:
            return
        try:
            if self._cls(_Le8) == 'Text':
                _Le9 = _Le8.get('sel.first', 'sel.last') if _Le8.tag_ranges('sel') else _Le8.get('1.0', 'end-1c')
            else:
                _Le9 = _Le8.selection_get()
        except Exception:
            _Le9 = ''
        if _Le9:
            self.root.clipboard_clear()
            self.root.clipboard_append(_Le9)

    def _cut(self):
        _Lfa = self._target
        if not _Lfa:
            return
        self._copy()
        try:
            if self._cls(_Lfa) == 'Text':
                if _Lfa.tag_ranges('sel'):
                    _Lfa.delete('sel.first', 'sel.last')
            else:
                _Lfa.delete('sel.first', 'sel.last')
        except Exception:
            pass

    def _paste(self):
        _Lfb = self._target
        if not _Lfb:
            return
        _Lfc = self._read_clip()
        if not _Lfc:
            return
        self._insert_text(_Lfb, _Lfc)

    def _select_all(self):
        _Lfd = self._target
        if not _Lfd:
            return
        try:
            if self._cls(_Lfd) == 'Text':
                _Lfd.tag_add('sel', '1.0', 'end-1c')
            else:
                _Lfd.selection_range(0, 'end')
                _Lfd.icursor('end')
        except Exception:
            pass

    def _read_clip(self):
        try:
            return self.root.clipboard_get()
        except Exception:
            return ''

    def _insert_text(self, _Lfe, _Lff):
        try:
            if str(_Lfe.cget('state')) == 'readonly':
                return
        except Exception:
            pass
        try:
            try:
                _Lfe.delete('sel.first', 'sel.last')
            except Exception:
                pass
            _Lfe.insert('insert', _Lff)
        except Exception:
            pass

    def popup(self, _Lfg):
        _Lfh = self._widget(_Lfg)
        if _Lfh is None:
            return 'break'
        self._target = _Lfh
        try:
            self.menu.tk_popup(_Lfg.x_root, _Lfg.y_root)
        finally:
            self.menu.grab_release()
        return 'break'

def _al(_Lea):
    _Leb = _ak(_Lea)
    for _Lec in INPUT_CLASSES:
        try:
            _Lea.bind_class(_Lec, '<Control-KeyPress>', _Leb.on_control_key, add='+')
        except Exception:
            pass
    return _Leb

class App:

    def __init__(self):
        self.root_ready = True
        self.config_path = _i()
        self.config = {}
        self.profiles = []
        self.selected = None
        self._base_signature = ''
        self._history = []
        self._balance_results = queue.Queue()
        self._lang = 'ru'
        self._build_root()
        self.load()

    def _build_root(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry('1160x780')
        self.root.minsize(960, 640)
        self.root.configure(bg=_b.bg)
        _c(self.root)
        self.clipboard = _al(self.root)
        self._build()
        try:
            self.clipboard.bind_tree(self.root)
        except Exception:
            pass
        self.root.bind('<Control-z>', lambda e: self.undo_last())
        self.root.bind('<Control-Z>', lambda e: self.undo_last())

    def _build(self):
        _Lfi = self.root
        _Lfj = tk.Frame(_Lfi, bg=_b.bg)
        _Lfj.pack(fill='x', padx=16, pady=(14, 4))
        _Lfk = tk.Frame(_Lfj, bg=_b.bg)
        _Lfk.pack(side='left', padx=(2, 20))
        tk.Label(_Lfk, text='OPENCODE', bg=_b.bg, fg=_b.cyan, font=_b.mono_big).pack(anchor='w')
        tk.Label(_Lfk, text='ПРОВАЙДЕРЫ И МОДЕЛИ', bg=_b.bg, fg=_b.ink_dim, font=_b.mono_small).pack(anchor='w')
        _Lfl = tk.Frame(_Lfj, bg=_b.bg)
        _Lfl.pack(side='left', fill='x', expand=True, padx=8)
        tk.Label(_Lfl, text='КОНФИГУРАЦИЯ', bg=_b.bg, fg=_b.ink_dim, font=_b.mono_small).pack(anchor='w')
        self.var_path = tk.StringVar(value=str(self.config_path))
        ttk.Entry(_Lfl, textvariable=self.var_path, font=_b.mono).pack(fill='x', pady=(2, 0))
        _Lfm = tk.Frame(_Lfj, bg=_b.bg)
        _Lfm.pack(side='right', padx=(8, 2))
        ttk.Button(_Lfm, text='ОТКРЫТЬ ПАПКУ', command=self._open_folder).pack(side='left', padx=3)
        ttk.Button(_Lfm, text='ПЕРЕЗАГРУЗИТЬ', command=self.load).pack(side='left', padx=3)
        _e(_Lfi, color=_b.cyan).pack(fill='x', padx=16, pady=(6, 0))
        _Lfn = tk.Frame(_Lfi, bg=_b.bg)
        _Lfn.pack(fill='both', expand=True, padx=16, pady=8)
        _Lfo = _d(_Lfn, width=430, radius=20, fill=_b.panel_fill, outline=_b.panel_edge, thickness=1, bg=_b.bg)
        _Lfo.pack(side='left', fill='y', padx=(0, 10))
        _Lfp = _Lfo.inner
        _Lfq = tk.Frame(_Lfp, bg=_b.bg_panel)
        _Lfq.pack(fill='x', padx=10, pady=(10, 6))
        tk.Label(_Lfq, text='ПРОФИЛИ', bg=_b.bg_panel, fg=_b.cyan, font=_b.mono_title).pack(side='left')
        self.lbl_count = tk.Label(_Lfq, text='0', bg=_b.bg_panel, fg=_b.ink_dim, font=_b.mono_small)
        self.lbl_count.pack(side='right')
        _Lfr = tk.Frame(_Lfp, bg=_b.bg_panel)
        _Lfr.pack(fill='both', expand=True, padx=8, pady=4)
        self.tree = ttk.Treeview(_Lfr, columns=('name', 'url'), show='headings', selectmode='browse')
        self.tree.heading('name', text='ПРОФИЛЬ')
        self.tree.heading('url', text='URL')
        self.tree.column('name', width=150, anchor='w')
        self.tree.column('url', width=245, anchor='w')
        _Lfs = ttk.Scrollbar(_Lfr, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=_Lfs.set)
        self.tree.pack(side='left', fill='both', expand=True)
        _Lfs.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._on_select())
        self.tree.bind('<Double-1>', lambda e: self.edit_profile())
        _Lft = tk.Frame(_Lfp, bg=_b.bg_panel)
        _Lft.pack(fill='x', padx=8, pady=(6, 10))
        ttk.Button(_Lft, text='+ ДОБАВИТЬ', style='Accent.TButton', command=self.add_profile).pack(side='left', padx=(2, 3), pady=4)
        ttk.Button(_Lft, text='ИЗМЕНИТЬ', command=self.edit_profile).pack(side='left', padx=3)
        ttk.Button(_Lft, text='УДАЛИТЬ', style='Danger.TButton', command=self.delete_profile).pack(side='left', padx=3)
        _Lfu = _d(_Lfn, radius=20, fill=_b.panel_fill, outline=_b.panel_edge, thickness=1, bg=_b.bg)
        _Lfu.pack(side='left', fill='both', expand=True)
        _Lfv = _Lfu.inner
        _Lfw = tk.Frame(_Lfv, bg=_b.bg_panel)
        _Lfw.pack(fill='x', padx=12, pady=(10, 2))
        tk.Label(_Lfw, text='ПРОФИЛЬ', bg=_b.bg_panel, fg=_b.ink_dim, font=_b.mono_small).pack(anchor='w')
        self.lbl_title = tk.Label(_Lfw, text='— НЕ ВЫБРАН —', bg=_b.bg_panel, fg=_b.cyan, font=_b.mono_big)
        self.lbl_title.pack(anchor='w', pady=(2, 0))
        _Lfx = tk.Frame(_Lfv, bg=_b.bg_panel)
        _Lfx.pack(fill='x', padx=10, pady=(8, 4))
        self.detail_vars = {}
        for _Lf6, (_Lf8, _Lf9) in enumerate([('ID', 'id'), ('НАЗВАНИЕ', 'display_name'), ('URL', 'base_url'), ('API KEY', 'api_key'), ('ТРАНСПОРТ', 'package')]):
            tk.Label(_Lfx, text=_Lf8, bg=_b.bg_panel, fg=_b.ink_dim, font=_b.mono_small, width=11, anchor='w').grid(row=_Lf6, column=0, sticky='w', padx=(6, 8), pady=3)
            _Lf7 = tk.StringVar()
            self.detail_vars[_Lf9] = _Lf7
            _Lf3 = ttk.Entry(_Lfx, textvariable=_Lf7, font=_b.mono)
            _Lf3.grid(row=_Lf6, column=1, sticky='ew', padx=6, pady=3)
            _Lf3.configure(state='readonly')
            if _Lf9 == 'api_key':
                _Lf3.configure(show='•')
                ttk.Button(_Lfx, text='ПОКАЗАТЬ', command=lambda e=_Lf3: self._toggle_entry(e)).grid(row=_Lf6, column=2, padx=6)
        _Lfx.columnconfigure(1, weight=1)
        _Lfy = tk.Frame(_Lfv, bg=_b.bg_panel)
        _Lfy.pack(fill='x', padx=12, pady=(10, 0))
        tk.Label(_Lfy, text='БАЛАНС', bg=_b.bg_panel, fg=_b.ink_dim, font=_b.mono_small).pack(side='left')
        self.lbl_balance_main = tk.Label(_Lfy, text='—', bg=_b.bg_panel, fg=_b.ink_dim, font=_b.mono)
        self.lbl_balance_main.pack(side='left', padx=(10, 8))
        self.btn_balance_main = ttk.Button(_Lfy, text='ОБНОВИТЬ', command=self.request_balance)
        self.btn_balance_main.pack(side='right', padx=2)
        self.lbl_balance_when = tk.Label(_Lfy, text='', bg=_b.bg_panel, fg=_b.cyan_dim, font=_b.mono_small)
        self.lbl_balance_when.pack(side='right', padx=8)
        self.lbl_balance_est_main = tk.Label(_Lfv, text='', bg=_b.bg_panel, fg=_b.cyan_soft, font=_b.mono_small, anchor='w')
        self.lbl_balance_est_main.pack(fill='x', padx=18, pady=(1, 0))
        _Lfz = tk.Frame(_Lfv, bg=_b.bg_panel)
        _Lfz.pack(fill='x', padx=12, pady=(10, 2))
        tk.Label(_Lfz, text='МОДЕЛИ ПРОФИЛЯ', bg=_b.bg_panel, fg=_b.ink_dim, font=_b.mono_small).pack(side='left')
        self.lbl_models_count = tk.Label(_Lfz, text='', bg=_b.bg_panel, fg=_b.amber, font=_b.mono_small)
        self.lbl_models_count.pack(side='right')
        self.lst_models = tk.Listbox(_Lfv, height=4, bg=_b.bg_input, fg=_b.cyan_soft, selectbackground='#0b3547', selectforeground=_b.cyan, relief='flat', font=_b.mono_small, highlightthickness=1, highlightbackground=_b.line)
        self.lst_models.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        self.lst_models.bind('<Double-1>', lambda e: self.make_default())
        self.lst_models.bind('<Return>', lambda e: self.make_default())
        _Lf0 = tk.Frame(_Lfv, bg=_b.bg_panel)
        _Lf0.pack(fill='x', padx=12, pady=(0, 6))
        ttk.Button(_Lf0, text='ИЗМЕНИТЬ ПРОФИЛЬ…', style='Accent.TButton', command=self.edit_profile).pack(side='left', fill='x', expand=True, padx=(2, 4), pady=4)
        ttk.Button(_Lf0, text='ПО УМОЛЧАНИЮ', command=self.make_default).pack(side='left', fill='x', expand=True, padx=(4, 2), pady=4)
        _e(_Lfi, color=_b.amber).pack(fill='x', padx=16, pady=(2, 0))
        _Lf1 = tk.Frame(_Lfi, bg=_b.bg)
        _Lf1.pack(fill='x', padx=16, pady=(8, 6))
        _Lf2 = tk.Frame(_Lf1, bg=_b.bg)
        _Lf2.pack(fill='x')
        tk.Label(_Lf2, text='МОДЕЛЬ ПО УМОЛЧАНИЮ', bg=_b.bg, fg=_b.ink_dim, font=_b.mono_small).pack(side='left', padx=(4, 10))
        self.var_default_model = tk.StringVar()
        _Lf3 = ttk.Entry(_Lf2, textvariable=self.var_default_model, font=_b.mono)
        _Lf3.configure(state='readonly')
        _Lf3.pack(side='left', fill='x', expand=True, padx=4, pady=4)
        ttk.Button(_Lf2, text='ПРИМЕНИТЬ К КОНФИГУ', style='Accent.TButton', command=self.write_config).pack(side='left', padx=(8, 4))
        self.lbl_dirty = tk.Label(_Lf2, text='', bg=_b.bg, fg=_b.amber, font=_b.mono_small)
        self.lbl_dirty.pack(side='left', padx=(6, 2))
        _Lf4 = tk.Frame(_Lf1, bg=_b.bg)
        _Lf4.pack(fill='x', pady=(6, 0))
        ttk.Button(_Lf4, text='ИСТОРИЯ И ОТКАТ…', command=self.open_history).pack(side='left', padx=3)
        ttk.Button(_Lf4, text='СНИМОК СЕЙЧАС', command=lambda: self.snapshot_now('Ручной снимок')).pack(side='left', padx=3)
        ttk.Button(_Lf4, text='ЭКСПОРТ ВСЕХ ПРОФИЛЕЙ…', command=self.export_profile).pack(side='left', padx=3)
        ttk.Button(_Lf4, text='ИМПОРТ ПРОФИЛЕЙ…', command=self.import_profile).pack(side='left', padx=3)
        self.hist_info = tk.Label(_Lf4, text='Снимков: 0', bg=_b.bg, fg=_b.cyan_soft, font=_b.mono_small, anchor='e')
        self.hist_info.pack(side='right', padx=(6, 10))
        tk.Frame(_Lf4, bg=_b.bg).pack(side='left', fill='x', expand=True)
        tk.Label(_Lfi, text='CTRL+Z — ОТКАТ К ПРЕДЫДУЩЕЙ ВЕРСИИ', bg=_b.bg, fg=_b.cyan_dim, font=_b.mono_small).pack(anchor='w', padx=22, pady=(0, 2))
        _Lf5 = tk.Frame(_Lfi, bg=_b.bg_panel_hi, height=26)
        _Lf5.pack(fill='x', side='bottom')
        _Lf5.pack_propagate(False)
        self.status = tk.Label(_Lf5, text='', bg=_b.bg_panel_hi, fg=_b.cyan_soft, font=_b.mono_small, anchor='w')
        self.status.pack(side='left', fill='x', expand=True, padx=14)

    def _toggle_entry(self, _Lga):
        _Lgb = _Lga.cget('show') == ''
        _Lga.configure(show='•' if _Lgb else '')

    def load(self):
        _Lgc = Path(self.var_path.get().strip() or _i())
        self.config_path = _Lgc
        try:
            self.config = _k(_Lgc)
            self.profiles = _y(self.config)
        except Exception as _Lgd:
            messagebox.showerror('Чтение конфига', 'Не удалось прочитать:\n%s\n\n%s' % (_Lgc, _Lgd))
            self.config, self.profiles = ({}, [])
        self.var_default_model.set(_z(self.config) or '(не задана)')
        self._render_list()
        self._refresh_history()
        self._base_signature = self._signature()
        self._set_status('ЗАГРУЖЕНО ПРОФИЛЕЙ: %d   •   %s' % (len(self.profiles), _Lgc))

    def _signature(self) -> str:
        try:
            return json.dumps([self.config, self.profiles], sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return ''

    def _is_dirty(self) -> bool:
        return self._base_signature != self._signature()

    def _refresh_dirty_marker(self):
        _Lge = getattr(self, 'lbl_dirty', None)
        if _Lge is None:
            return
        try:
            _Lge.configure(text='● ЕСТЬ НЕСОХРАНЁННЫЕ ИЗМЕНЕНИЯ' if self._is_dirty() else '')
        except Exception:
            pass

    def _set_status(self, _Lgf):
        try:
            self.status.configure(text=_Lgf)
        except Exception:
            pass

    def _render_list(self):
        self.tree.delete(*self.tree.get_children())
        for _Lgg in self.profiles:
            self.tree.insert('', 'end', iid=_Lgg['id'], values=(_Lgg['display_name'], _Lgg['base_url']))
        try:
            self.lbl_count.configure(text=str(len(self.profiles)))
        except Exception:
            pass
        if self.profiles:
            self.tree.selection_set(self.profiles[0]['id'])
            self._on_select()
        else:
            self._clear_details()
        self._refresh_dirty_marker()

    def _find(self, _Lgh):
        for _Lgi in self.profiles:
            if _Lgi['id'] == _Lgh:
                return _Lgi
        return None

    def _on_select(self):
        _Lgj = self.tree.selection()
        if not _Lgj:
            self._clear_details()
            return
        self.selected = _Lgj[0]
        _Lgk = self._find(self.selected)
        if not _Lgk:
            return
        self.lbl_title.configure(text=(_Lgk['display_name'] or _Lgk['id']).upper())
        for _Lgl in ('id', 'display_name', 'base_url', 'package'):
            self.detail_vars[_Lgl].set(_Lgk[_Lgl])
        _Lgl = _Lgk['api_key']
        self.detail_vars['api_key'].set('(не задан)' if not _Lgl else _Lgl[:6] + '…' + _Lgl[-4:] if len(_Lgl) > 12 else '••••')
        self.lst_models.delete(0, 'end')
        for _Lgm in _Lgk['models']:
            self.lst_models.insert('end', _Lgm)
        if _Lgk['models']:
            _Lgn = self.var_default_model.get()
            _Lgo = str(_Lgk['id']) + '/'
            _Lgp = 0
            if _Lgn.startswith(_Lgo):
                _Lgq = _Lgn[len(_Lgo):]
                if _Lgq in _Lgk['models']:
                    _Lgp = _Lgk['models'].index(_Lgq)
            self.lst_models.selection_set(_Lgp)
            self.lst_models.see(_Lgp)
        else:
            self.lst_models.insert('end', '(модели не выбраны)')
        try:
            self.lbl_models_count.configure(text=str(len(_Lgk['models'])))
            self.lst_models.configure(height=max(3, min(10, len(_Lgk['models']) or 3)))
        except Exception:
            pass
        self._show_balance(_Lgk)
        if not _Lgk.get('_balance') and (not _Lgk.get('_balance_tried')):
            _Lgk['_balance_tried'] = True
            self.root.after(250, self.request_balance)

    def _clear_details(self):
        self.lbl_title.configure(text='— НЕ ВЫБРАН —')
        for _Lgr in self.detail_vars.values():
            _Lgr.set('')
        self.lst_models.delete(0, 'end')

    def add_profile(self):
        _Lgs = _aa(self, None)
        self.root.wait_window(_Lgs)
        _Lgt = _Lgs.result
        if not _Lgt:
            return
        self.profiles.append(self._from_dialog(_Lgt))
        self._render_list()
        self.tree.selection_set(_Lgt['id'])
        self._set_status('ДОБАВЛЕН ПРОФИЛЬ %s (НЕ СОХРАНЁН)' % _Lgt['id'])
        self._refresh_dirty_marker()
        if _Lgt.get('set_default') and _Lgt['models']:
            self.var_default_model.set('%s/%s' % (_Lgt['id'], _Lgt['models'][0]))

    def edit_profile(self):
        if not self.selected:
            messagebox.showinfo('Изменить', 'Выберите профиль в списке', parent=self.root)
            return
        _Lgu = self._find(self.selected)
        if not _Lgu:
            return
        _Lgv = _aa(self, _Lgu)
        self.root.wait_window(_Lgv)
        _Lgw = _Lgv.result
        if not _Lgw:
            return
        _Lgx = self.profiles.index(_Lgu)
        self.profiles[_Lgx] = self._from_dialog(_Lgw)
        self.selected = _Lgw['id']
        self._render_list()
        self._set_status('ПРОФИЛЬ %s ОБНОВЛЁН (НЕ СОХРАНЁН)' % _Lgw['id'])
        self._refresh_dirty_marker()

    def _from_dialog(self, _Lgy):
        return {'id': _Lgy['id'], 'display_name': _Lgy['display_name'], 'base_url': _Lgy['base_url'], 'api_key': _Lgy['api_key'], 'package': _Lgy['package'], 'models': list(_Lgy['models']), 'known_models': list(_Lgy['known_models']), 'coefficient': _Lgy.get('coefficient') or '', 'extra_settings': _Lgy.get('extra_settings') or {}, '_raw': _Lgy.get('_raw')}

    def delete_profile(self):
        _Lgz = self._find(self.selected) if self.selected else None
        if not _Lgz:
            messagebox.showinfo('Удалить', 'Выберите профиль в списке', parent=self.root)
            return
        if not messagebox.askyesno('Удалить профиль', 'Удалить профиль «%s»?\n\nИз конфига он исчезнет после «ПРИМЕНИТЬ К КОНФИГУ».' % _Lgz['display_name'], parent=self.root):
            return
        self.profiles.remove(_Lgz)
        self.selected = None
        self._render_list()
        self._set_status('ПРОФИЛЬ %s УДАЛЁН ИЗ СПИСКА' % _Lgz['id'])
        self._refresh_dirty_marker()

    def make_default(self):
        _Lg0 = self._find(self.selected) if self.selected else None
        if not _Lg0 or not _Lg0['models']:
            messagebox.showinfo('По умолчанию', 'У выбранного профиля нет моделей', parent=self.root)
            return
        _Lg1 = self._selected_model()
        if not _Lg1:
            if len(_Lg0['models']) == 1:
                _Lg1 = _Lg0['models'][0]
            else:
                _Lg1 = self._ask_model(_Lg0)
                if not _Lg1:
                    return
        self._apply_default(_Lg0, _Lg1)

    def _selected_model(self):
        try:
            _Lg2 = self.lst_models.curselection()
            if _Lg2:
                _Lg3 = self.lst_models.get(_Lg2[0])
                if _Lg3 and _Lg3 != '(модели не выбраны)':
                    return _Lg3
        except Exception:
            pass
        return None

    def _apply_default(self, _Lg4, _Lg5):
        self.var_default_model.set('%s/%s' % (_Lg4['id'], _Lg5))
        self._set_status('МОДЕЛЬ ПО УМОЛЧАНИЮ: %s/%s (НЕ СОХРАНЕНО)' % (_Lg4['id'], _Lg5))
        self._refresh_dirty_marker()

    def _ask_model(self, profile):
        win = tk.Toplevel(self.root)
        win.title('МОДЕЛЬ ПО УМОЛЧАНИЮ')
        win.configure(bg=_b.bg)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text='ВЫБЕРИТЕ МОДЕЛЬ', bg=_b.bg, fg=_b.cyan, font=_b.mono_title).pack(anchor='w', padx=14, pady=(12, 6))
        lb = tk.Listbox(win, height=min(12, len(profile['models'])), width=62, bg=_b.bg_panel, fg=_b.ink, selectbackground='#0b3547', selectforeground=_b.cyan, font=_b.mono_small, relief='flat', highlightthickness=1, highlightbackground=_b.line)
        for mid in profile['models']:
            lb.insert('end', mid)
        lb.pack(fill='both', expand=True, padx=14, pady=4)
        lb.selection_set(0)
        chosen = {'value': None}

        def ok():
            _Lig = lb.curselection()
            if _Lig:
                chosen['value'] = profile['models'][_Lig[0]]
            win.destroy()
        row = tk.Frame(win, bg=_b.bg)
        row.pack(fill='x', padx=14, pady=(4, 12))
        ttk.Button(row, text='ОК', style='Accent.TButton', command=ok).pack(side='right', padx=4)
        ttk.Button(row, text='ОТМЕНА', command=win.destroy).pack(side='right')
        win.wait_window()
        return chosen['value']

    def request_balance(self):
        if not hasattr(self, '_balance_results'):
            self._balance_results = queue.Queue()
        profile = self._find(self.selected) if self.selected else None
        if not profile:
            messagebox.showinfo('Баланс', 'Выберите профиль в списке', parent=self.root)
            return
        self.lbl_balance_main.configure(text='ЗАГРУЗКА…', fg=_b.ink_dim)
        self.lbl_balance_when.configure(text='запрос…')
        try:
            self.btn_balance_main.configure(state='disabled')
        except Exception:
            pass

        def work():
            try:
                self._balance_results.put((profile['id'], _u(profile['base_url'], profile['api_key']), None))
            except Exception as _Lih:
                self._balance_results.put((profile['id'], None, _Lih))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(120, self._poll_balance)

    def _poll_balance(self):
        try:
            _Lg7, _Lg8, _Lg9 = self._balance_results.get_nowait()
        except queue.Empty:
            self.root.after(120, self._poll_balance)
            return
        try:
            self.btn_balance_main.configure(state='normal')
        except Exception:
            pass
        _Lg6 = self._find(_Lg7)
        if _Lg6 is None:
            return
        if _Lg9 is not None:
            self.lbl_balance_main.configure(text='нет данных', fg=_b.red)
            self.lbl_balance_when.configure(text=str(_Lg9)[:70])
            _Lg6['_balance'] = None
            _Lg6['_balance_error'] = str(_Lg9)
            return
        _Lg6['_balance'] = _Lg8
        _Lg6['_balance_error'] = None
        _Lg6['_balance_at'] = datetime.now()
        if _Lg7 == self.selected:
            self._show_balance(_Lg6)
        if not _Lg6.get('_balance') and (not _Lg6.get('_balance_tried')):
            _Lg6['_balance_tried'] = True
            self.root.after(250, self.request_balance)

    def _show_balance(self, _Lha):
        _Lhb = _Lha.get('_balance')
        _Lhc = _Lha.get('_balance_at')
        try:
            if _Lhb:
                self.lbl_balance_main.configure(text=_Lhb.get('text') or '—', fg=_b.green)
                self.lbl_balance_when.configure(text='обновлено %s' % _Lhc.strftime('%H:%M:%S') if _Lhc else '')
                _Lhd = str(_Lha.get('coefficient') or '').strip()
                _Lhe = _t(_Lhb.get('tokens'), _Lhd) if _Lhd else {}
                if _Lhe:
                    self.lbl_balance_est_main.configure(text='≈ %s при коэффициенте %s' % (_Lhe['text'], _Lhd))
                elif not _Lhd:
                    self.lbl_balance_est_main.configure(text='коэффициент не задан — укажите в профиле, чтобы видеть остаток в токенах')
                else:
                    self.lbl_balance_est_main.configure(text='')
            else:
                _Lhf = _Lha.get('_balance_error')
                self.lbl_balance_main.configure(text='—' if not _Lhf else 'нет данных', fg=_b.ink_dim if not _Lhf else _b.red)
                self.lbl_balance_when.configure(text=(_Lhf or '')[:70])
                self.lbl_balance_est_main.configure(text='')
        except Exception:
            pass

    def _open_folder(self):
        try:
            os.startfile(str(self.config_path.parent))
        except Exception as _Lhg:
            messagebox.showerror('Папка', str(_Lhg), parent=self.root)

    def _refresh_history(self):
        try:
            self._history = _m(self.config_path)
        except Exception:
            self._history = []
        _Lhh = getattr(self, 'hist_info', None)
        if _Lhh is not None:
            _Lhi = self._history[0]['time'].strftime('%d.%m.%Y %H:%M:%S') if self._history and self._history[0].get('time') else '—'
            _Lhh.configure(text='Снимков: %d  •  последний: %s' % (len(self._history), _Lhi))

    def open_history(self):
        _ab(self)

    def snapshot_now(self, _Lhj=''):
        try:
            _Lhl = _n(self.config_path)
        except Exception as _Lhk:
            messagebox.showerror('Снимок', str(_Lhk), parent=self.root)
            return None
        if _Lhl:
            self._refresh_history()
            self._set_status((_Lhj + '  •  ' if _Lhj else '') + 'СНИМОК: ' + _Lhl.name)
        return _Lhl

    def undo_last(self):
        if self._is_dirty():
            if not messagebox.askyesno('Откат', 'Есть неприменённые изменения в форме. Откатить файл к предыдущей версии?', parent=self.root):
                return
        self._refresh_history()
        if not self._history:
            messagebox.showinfo('Откат', 'Снимков ещё нет.', parent=self.root)
            return
        self.quick_restore(self._history[0])

    def quick_restore(self, _Lhm):
        if not _Lhm.get('valid'):
            messagebox.showerror('Откат', 'Снимок повреждён:\n%s' % _Lhm['name'], parent=self.root)
            return
        _Lhn = _Lhm['time'].strftime('%d.%m.%Y %H:%M:%S') if _Lhm.get('time') else '?'
        if not messagebox.askyesno('Откатить конфиг?', 'Восстановить версию от %s?\n\nФайл: %s\nПровайдеры: %s\nМодель: %s\n\nТекущая версия тоже сохранится в историю.' % (_Lhn, _Lhm['path'].name, ', '.join(_Lhm.get('providers') or []) or '(нет)', _Lhm.get('model') or '(не задана)'), parent=self.root):
            return
        try:
            _Lhp = _q(self.config_path, _Lhm['path'])
        except Exception as _Lho:
            messagebox.showerror('Откат', str(_Lho), parent=self.root)
            return
        self.load()
        self._set_status('ОТКАТ ВЫПОЛНЕН. ВЕРСИЯ ДО ОТКАТА: %s' % (_Lhp.name if _Lhp else '—'))
        messagebox.showinfo('Откат', 'Конфиг восстановлен из снимка %s.\nОткат самого отката: %s' % (_Lhm['name'], _Lhp.name if _Lhp else '—'), parent=self.root)

    def write_config(self):
        _Lhq = self._is_dirty()
        try:
            _Lht = _5(self.config, self.profiles)
            _Lhu = self.var_default_model.get().strip()
            if _Lhu and _Lhu != '(не задана)':
                _Lht['model'] = _Lhu
            _Lhv = _p(self.config_path, _Lht)
        except Exception as _Lhr:
            messagebox.showerror('Запись конфига', str(_Lhr), parent=self.root)
            return
        self.config = _Lht
        self.profiles = _y(self.config)
        self._base_signature = self._signature()
        self._render_list()
        self._refresh_history()
        self._refresh_dirty_marker()
        _Lhs = 'Конфиг записан. Предыдущая версия: %s' % (_Lhv.name if _Lhv else '—')
        self._set_status(_Lhs.upper())
        messagebox.showinfo('Готово', '%s\n\nФайл: %s\n\nОткат: кнопка «ИСТОРИЯ И ОТКАТ…» или Ctrl+Z' % (_Lhs, self.config_path), parent=self.root)
        if not _Lhq:
            self._set_status('СОХРАНЕНА КОНТРОЛЬНАЯ ТОЧКА: ' + (_Lhv.name if _Lhv else '—'))

    def export_profile(self):
        if not self.profiles:
            messagebox.showinfo('Экспорт профилей', 'Список профилей пуст — нечего сохранять', parent=self.root)
            return
        _Lhw = _7(self.profiles, self.var_default_model.get())
        _Lhx = str(Path.home() / 'Downloads')
        _Lhy = filedialog.asksaveasfilename(parent=self.root, title='Экспорт всех профилей моделей', defaultextension='.json', initialdir=_Lhx if Path(_Lhx).is_dir() else str(Path.home()), initialfile='opencode-profiles.json', filetypes=[('JSON файлы', '*.json'), ('Все файлы', '*.*')])
        if not _Lhy:
            return
        _Lhz = Path(_Lhy)
        if _Lhz.suffix.lower() != '.json':
            _Lhz = _Lhz.with_suffix('.json')
        try:
            _Lhz.parent.mkdir(parents=True, exist_ok=True)
            _Lhz.write_text(json.dumps(_Lhw, indent=2, ensure_ascii=False), encoding='utf-8')
        except PermissionError:
            messagebox.showerror('Экспорт', 'Нет доступа к папке: %s\n\nВыберите другую папку (например, Загрузки).' % _Lhz.parent, parent=self.root)
            return
        except Exception as _Lh0:
            messagebox.showerror('Экспорт', 'Не удалось сохранить файл:\n%s\n\n%s' % (_Lhz, _Lh0), parent=self.root)
            return
        if not _Lhz.exists():
            messagebox.showerror('Экспорт', 'Файл не создан: %s' % _Lhz, parent=self.root)
            return
        self._set_status('ЭКСПОРТИРОВАНО ПРОФИЛЕЙ: %d → %s' % (len(_Lhw['profiles']), _Lhz))
        messagebox.showinfo('Экспорт', 'Сохранено профилей: %d\n\nФайл:\n%s\n\nРазмер: %d байт' % (len(_Lhw['profiles']), _Lhz, _Lhz.stat().st_size), parent=self.root)

    def import_profile(self):
        _Lh1 = str(Path.home() / 'Downloads')
        _Lh2 = filedialog.askopenfilename(parent=self.root, title='Импорт профилей', initialdir=_Lh1 if Path(_Lh1).is_dir() else str(Path.home()), filetypes=[('JSON файлы', '*.json'), ('Все файлы', '*.*')])
        if not _Lh2:
            return
        _Lh3 = Path(_Lh2)
        if not _Lh3.exists():
            messagebox.showerror('Импорт', 'Файл не найден:\n%s' % _Lh3, parent=self.root)
            return
        try:
            _Lh9 = json.loads(_Lh3.read_text(encoding='utf-8-sig'))
        except Exception as _Lh4:
            messagebox.showerror('Импорт', 'Не удалось прочитать файл:\n%s\n\n%s' % (_Lh3, _Lh4), parent=self.root)
            return
        try:
            _Lib, _Lic = _9(_Lh9)
        except ValueError as _Lh4:
            messagebox.showerror('Импорт', '%s\n\nФайл: %s' % (_Lh4, _Lh3), parent=self.root)
            return
        _Lh5 = [_Lid['id'] for _Lid in _Lib if self._find(_Lid['id']) is not None]
        if _Lh5:
            if not messagebox.askyesno('Импорт', 'Уже есть профили с такими ID:\n%s\n\nЗаменить их?' % ', '.join(_Lh5), parent=self.root):
                return
        _Lh6 = _Lh7 = 0
        for _Lh8 in _Lib:
            _Lia = self._find(_Lh8['id'])
            if _Lia is not None:
                self.profiles[self.profiles.index(_Lia)] = _Lh8
                _Lh7 += 1
            else:
                self.profiles.append(_Lh8)
                _Lh6 += 1
        if _Lic:
            self.var_default_model.set(_Lic)
        self.selected = _Lib[0]['id']
        self._render_list()
        self._set_status('ИМПОРТИРОВАНО ПРОФИЛЕЙ: %d (новых %d, заменено %d) — НЕ СОХРАНЁН' % (len(_Lib), _Lh6, _Lh7))
        messagebox.showinfo('Импорт', 'Импортировано профилей: %d\nНовых: %d\nЗаменено: %d\n\nНе забудьте «ПРИМЕНИТЬ К КОНФИГУ».' % (len(_Lib), _Lh6, _Lh7), parent=self.root)

    def run(self):
        self.root.mainloop()

def _am(_Led: str) -> bool:
    try:
        __import__(_Led)
        return True
    except Exception:
        return False
REQUIRED = {'certifi': ('certifi', 'актуальные корневые сертификаты для TLS')}
OPTIONAL = {'PIL': ('Pillow', 'запасной захват экрана диагностики')}

def _an(_Lee: str) -> tuple[bool, str]:
    import subprocess
    try:
        _Leg = subprocess.run([sys.executable, '-m', 'pip', 'install', '--user', '--upgrade', '--quiet', _Lee], capture_output=True, text=True, timeout=240)
        if _Leg.returncode == 0:
            return (True, '')
        _Leh = (_Leg.stderr or _Leg.stdout or '').strip().splitlines()
        return (False, _Leh[-1] if _Leh else 'pip завершился с кодом %d' % _Leg.returncode)
    except Exception as _Lef:
        return (False, str(_Lef))

def _ao() -> list:
    _Lei = []
    if not _am('tkinter'):
        return ['tkinter не найден — переустановите Python с компонентом Tcl/Tk']
    _Lej = []
    for _Lek, (_Lel, _Lem) in REQUIRED.items():
        if not _am(_Lek):
            _Lej.append((_Lel, _Lem))
    if getattr(sys, 'frozen', False):
        _Lej = []
    if _Lej and (not _am('pip')):
        if getattr(sys, 'frozen', False):
            return _Lei
        try:
            import ensurepip
            ensurepip.bootstrap()
        except Exception:
            pass
    if _Lej and (not _am('pip')):
        _Lei.append('pip недоступен — автодогрузка невозможна (python -m ensurepip)')
        return _Lei
    for _Lel, _Lem in _Lej:
        _Lei.append('Догружаю %s — %s…' % (_Lel, _Lem))
        _Len, _Leo = _an(_Lel)
        if _Len and _am(_Lel):
            _Lei.append('%s установлен' % _Lel)
        else:
            _Lei.append('%s не установился: %s' % (_Lel, _Leo or 'неизвестная ошибка'))
    return _Lei

def _ap():
    if os.name != 'nt':
        return
    try:
        import ctypes
        _Lep = ctypes.windll.kernel32.GetConsoleWindow()
        if _Lep:
            ctypes.windll.user32.ShowWindow(_Lep, 0)
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

def main():
    _ap()
    _Leq = _ao()
    _Ler = App()
    if _Leq:
        _Ler._set_status('  •  '.join(_Leq))
    _Ler.run()
    return 0
if __name__ == '__main__':
    raise SystemExit(main())