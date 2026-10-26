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
    _T1 = '#010206'
    _T2 = '#04101a'
    _T3 = '#071a26'
    _T4 = '#020a12'
    _T5 = '#0e2b3a'
    _T6 = '#6df4ff'
    _T7 = '#a6f0ff'
    _T8 = '#2b6a7a'
    _T9 = '#ffc16b'
    _T10 = '#ff5568'
    _T11 = '#6dffb0'
    _T12 = '#d9fbff'
    _T13 = '#93c2d4'
    _T14 = ('Consolas', 10)
    _T15 = ('Consolas', 9)
    _T16 = ('Consolas', 12, 'bold')
    _T17 = ('Consolas', 18, 'bold')
    _T18 = ('Segoe UI', 10)

def _c(_Lb) -> None:
    _Lc = ttk.Style(_Lb)
    try:
        _Lc.theme_use('clam')
    except tk.TclError:
        pass
    _Lc.configure('.', background=_b._T1, foreground=_b._T12, fieldbackground=_b._T4, font=_b._T18, bordercolor=_b._T5)
    _Lc.configure('TFrame', background=_b._T1)
    _Lc.configure('TLabel', background=_b._T1, foreground=_b._T12, font=_b._T18)
    _Lc.configure('TButton', background=_b._T3, foreground=_b._T7, bordercolor=_b._T8, focuscolor=_b._T6, font=_b._T15, padding=(10, 6))
    _Lc.map('TButton', background=[('active', '#0b2c3d'), ('disabled', _b._T2)], foreground=[('disabled', _b._T8)])
    _Lc.configure('Accent.TButton', background='#0b3547', foreground=_b._T6, bordercolor=_b._T6, font=_b._T15, padding=(10, 6))
    _Lc.map('Accent.TButton', background=[('active', '#0f4a61')])
    _Lc.configure('Danger.TButton', background='#2a0d13', foreground=_b._T10, bordercolor='#7a2230', font=_b._T15, padding=(10, 6))
    _Lc.map('Danger.TButton', background=[('active', '#3d121b')])
    _Lc.configure('TEntry', fieldbackground=_b._T4, foreground=_b._T7, insertcolor=_b._T6, bordercolor=_b._T8, lightcolor=_b._T5, darkcolor=_b._T4, padding=6, font=_b._T14)
    _Lc.map('TEntry', bordercolor=[('focus', _b._T6)])
    _Lc.configure('TCombobox', fieldbackground=_b._T4, background=_b._T3, foreground=_b._T7, arrowcolor=_b._T6, bordercolor=_b._T8, padding=4)
    _Lc.map('TCombobox', fieldbackground=[('readonly', _b._T4)], foreground=[('readonly', _b._T7)])
    _Lc.configure('Treeview', background=_b._T2, fieldbackground=_b._T2, foreground=_b._T12, rowheight=24, font=_b._T15, bordercolor=_b._T5)
    _Lc.map('Treeview', background=[('selected', '#0b3547')], foreground=[('selected', _b._T6)])
    _Lc.configure('Treeview.Heading', background=_b._T3, foreground=_b._T13, font=_b._T15, relief='flat')
    _Lc.map('Treeview.Heading', background=[('active', '#0b2c3d')], foreground=[('active', _b._T6)])
    _Lc.configure('TScrollbar', background=_b._T3, troughcolor=_b._T1, bordercolor=_b._T1, arrowcolor=_b._T8)
    _Lc.map('TScrollbar', background=[('active', _b._T8)])

class _d(tk.Canvas):

    def __init__(self, master, height=2, color='#6df4ff', **kw):
        super().__init__(master, height=height, bg=_b._T1, highlightthickness=0, **kw)
        self._color = color
        self._h = height
        self.bind('<Configure>', lambda e: self._draw(e.width))

    def _draw(self, w):
        self.delete('all')
        h = self._h
        self.create_line(0, h // 2, w, h // 2, fill=_b._T5)
        self.create_line(0, h // 2, max(0, w // 3), h // 2, fill=self._color)
_CTX_CACHE: dict = {}

def _e():
    _Lg = []
    _Lf = os.environ.get('SSL_CERT_FILE')
    if _Lf:
        _Lg.append(Path(_Lf))
    try:
        import certifi
        _Lg.append(Path(certifi.where()))
    except Exception:
        pass
    _Le = Path(sys.prefix) / 'Lib' / 'site-packages'
    _Lg += [_Le / 'pip' / '_vendor' / 'certifi' / 'cacert.pem', Path('C:\\Program Files\\Git\\mingw64\\etc\\ssl\\certs\\ca-bundle.crt'), Path('C:\\Program Files\\Git\\usr\\ssl\\certs\\ca-bundle.crt'), Path('C:\\Program Files\\Common Files\\SSL\\cert.pem')]
    _Ld = []
    for _Lb in _Lg:
        try:
            if _Lb and _Lb.is_file() and (_Lb.stat().st_size > 4096):
                if str(_Lb).lower() not in [str(_Lc).lower() for _Lc in _Ld]:
                    _Ld.append(_Lb)
        except OSError:
            continue
    return _Ld

def _f(_Lb, _Lc):
    try:
        with socket.create_connection((_Lc, 443), timeout=8) as _Ld:
            with _Lb.wrap_socket(_Ld, server_hostname=_Lc):
                return True
    except ssl.SSLCertVerificationError:
        return False
    except Exception:
        return True

def _g(_Lb):
    _Lb = (_Lb or '').lower()
    if _Lb in _CTX_CACHE:
        return _CTX_CACHE[_Lb]
    _Ld = ssl.create_default_context()
    _Le = _f(_Ld, _Lb)
    if not _Le:
        for _Lc in _e():
            try:
                _Lf = ssl.create_default_context(cafile=str(_Lc))
            except Exception:
                continue
            if _f(_Lf, _Lb):
                _Ld, _Le = (_Lf, True)
                break
    _CTX_CACHE[_Lb] = _Ld
    return _Ld

def _h() -> Path:
    _Lc = os.environ.get('XDG_CONFIG_HOME')
    _Lb = Path(_Lc) if _Lc else Path.home() / '.config'
    return _Lb / 'opencode' / 'opencode.json'

def _i(_Lb: str) -> str:
    _Lg, _Lh, _Li, _Lc, _Ld = ([], 0, len(_Lb), False, False)
    while _Lh < _Li:
        _Lf = _Lb[_Lh]
        _Le = _Lb[_Lh + 1] if _Lh + 1 < _Li else ''
        if _Lc:
            _Lg.append(_Lf)
            if _Ld:
                _Ld = False
            elif _Lf == '\\':
                _Ld = True
            elif _Lf == '"':
                _Lc = False
            _Lh += 1
            continue
        if _Lf == '"':
            _Lc = True
            _Lg.append(_Lf)
            _Lh += 1
            continue
        if _Lf == '/' and _Le == '/':
            while _Lh < _Li and _Lb[_Lh] not in '\r\n':
                _Lh += 1
            continue
        if _Lf == '/' and _Le == '*':
            _Lh += 2
            while _Lh < _Li - 1 and (not (_Lb[_Lh] == '*' and _Lb[_Lh + 1] == '/')):
                _Lh += 1
            _Lh += 2
            continue
        _Lg.append(_Lf)
        _Lh += 1
    return re.sub(',(\\s*[}\\]])', '\\1', ''.join(_Lg))

def _j(_Lb: Path) -> dict:
    if not _Lb.exists():
        return {}
    _Ld = _Lb.read_text(encoding='utf-8-sig')
    try:
        _Lc = json.loads(_Ld)
    except json.JSONDecodeError:
        _Lc = json.loads(_i(_Ld))
    if not isinstance(_Lc, dict):
        raise ValueError('Корень конфига должен быть объектом JSON')
    return _Lc
HISTORY_LIMIT = 50

def _k(_Lb: Path) -> Path:
    return _Lb.parent / 'backups'

def _l(_Lb: Path) -> list:
    _Lh = []
    _Lg = []
    if _Lb.exists():
        _Lg += [_Lc for _Lc in _Lb.parent.glob(_Lb.name + '.bak-*') if _Lc.is_file()]
    _Lf = _k(_Lb)
    if _Lf.is_dir():
        _Lg += [_Lc for _Lc in _Lf.glob(_Lb.name + '.*.bak') if _Lc.is_file()]
    for _Lc in _Lg:
        _Le = {'path': _Lc, 'name': _Lc.name, 'time': None, 'valid': False, 'providers': [], 'model': '', '_mtime': 0}
        try:
            _Le['time'] = datetime.fromtimestamp(_Lc.stat().st_mtime)
            _Le['_mtime'] = _Lc.stat().st_mtime
        except OSError:
            pass
        try:
            _Ld = _j(_Lc)
            _Le['valid'] = True
            _Le['providers'] = list((_Ld.get('providers') or {}).keys())
            _Le['model'] = _y(_Ld)
        except Exception:
            pass
        _Lh.append(_Le)
    _Lh.sort(key=lambda e: e['_mtime'], reverse=True)
    return _Lh

def _m(_Lb: Path):
    if not _Lb.exists():
        return None
    _Lf = _k(_Lb)
    _Lf.mkdir(parents=True, exist_ok=True)
    _Le = datetime.now()
    _Ld = _Le.strftime('%Y%m%d-%H%M%S') + '-%03d' % (_Le.microsecond // 1000)
    _Lc = _Lf / ('%s.%s.bak' % (_Lb.name, _Ld))
    shutil.copy2(_Lb, _Lc)
    return _Lc

def _n(_Lb: Path, _Lc: int=HISTORY_LIMIT) -> None:
    _Lj = []
    _Li = _k(_Lb)
    if _Li.is_dir():
        _Lj.append((_Li, '*.bak'))
    _Lj.append((_Lb.parent, _Lb.name + '.bak-*'))
    for _Ld, _Le in _Lj:
        _Lg = sorted((_Lh for _Lh in _Ld.glob(_Le) if _Lh.is_file()), key=lambda p: _Lh.stat().st_mtime, reverse=True)
        for _Lf in _Lg[_Lc:]:
            try:
                _Lf.unlink()
            except OSError:
                pass

def _o(_Lb: Path, _Lc: dict):
    _Lb.parent.mkdir(parents=True, exist_ok=True)
    _Le = _m(_Lb)
    _Ld = _Lb.with_name(_Lb.name + '.tmp')
    _Ld.write_text(json.dumps(_Lc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(_Ld, _Lb)
    _n(_Lb)
    return _Le

def _p(_Lb: Path, _Lc: Path):
    _Lf = _j(_Lc)
    if not isinstance(_Lf, dict):
        raise ValueError('Снимок не содержит объект JSON')
    _Le = _m(_Lb)
    _Ld = _Lb.with_name(_Lb.name + '.tmp')
    _Ld.write_text(_Lc.read_text(encoding='utf-8-sig'), encoding='utf-8')
    os.replace(_Ld, _Lb)
    _n(_Lb)
    return _Le

def _q(_Lb: str) -> str:
    _Lb = (_Lb or '').strip()
    if not _Lb:
        return _Lb
    if not re.match('^[a-z][a-z0-9+.-]*://', _Lb, re.I):
        _Lb = 'https://' + _Lb
    return _Lb.rstrip('/')

def _r(_Lb: str, _Lc: str='', _Ld: float=15.0):
    _Lj = urllib.request.Request(_Lb, method='GET')
    _Lj.add_header('Accept', 'application/json')
    _Lj.add_header('User-Agent', 'opencode-provider-manager/2.0')
    if _Lc:
        _Lj.add_header('Authorization', 'Bearer ' + _Lc)
    _Li = urllib.parse.urlsplit(_Lb).hostname or ''
    try:
        with urllib.request.urlopen(_Lj, timeout=_Ld, context=_g(_Li)) as _Lh:
            _Lg = _Lh.read().decode('utf-8', 'replace')
            _Lf = _Lh.status
    except urllib.error.HTTPError as _Le:
        _Lg = _Le.read().decode('utf-8', 'replace')
        _Lf = _Le.code
    try:
        return (_Lf, json.loads(_Lg))
    except Exception:
        return (_Lf, _Lg)

def _s(_Lb, _Lc) -> dict:
    try:
        _Lb = float(_Lb)
        _Le = float(_Lc)
    except Exception:
        return {}
    if not _Le or _Le <= 0:
        return {}
    _Ld = _Lb / _Le
    return {'tokens_by_coef': int(_Ld), 'text': _v(int(_Ld))}

def _t(_Lb: str, _Lc: str) -> dict:
    _Lm = _q(_Lb)
    if not _Lm:
        raise ValueError('Не задан URL провайдера')
    _Ll = [_Lm]
    if re.search('/v\\d+[a-z]?$', _Lm, re.I):
        _Ll.append(_Lm[:_Lm.rfind('/')])
    _Lk = []
    for _Ld in _Ll:
        for _Le in ('/balance', '/credits', '/usage'):
            _Lj = _Ld + _Le
            try:
                _Lh, _Li = _r(_Lj, _Lc)
            except Exception as _Lg:
                _Lk.append('%s: %s' % (_Lj, _Lg))
                continue
            if _Lh == 404:
                continue
            if _Lh in (401, 403):
                raise PermissionError('Сервер отклонил ключ (HTTP %s)' % _Lh)
            if _Lh >= 400:
                _Lk.append('%s: HTTP %s' % (_Lj, _Lh))
                continue
            if not isinstance(_Li, dict):
                continue
            _Lf = _u(_Li)
            if _Lf:
                _Lf['url'] = _Lj
                _Lf['raw'] = _Li
                return _Lf
    raise RuntimeError('Эндпоинт баланса не найден. Проверено: %d адрес(ов). Последние ошибки: %s' % (len(_Lk), '; '.join(_Lk[-3:]) or '—'))

def _u(data: dict) -> dict:
    out = {'tokens': None, 'usd': None, 'text': ''}

    def as_int(_Lb):
        try:
            if isinstance(_Lb, bool) or _Lb is None:
                return None
            return int(float(_Lb))
        except Exception:
            return None

    def as_float(_Lb):
        try:
            if isinstance(_Lb, bool) or _Lb is None:
                return None
            return float(_Lb)
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
        parts.append(_v(out['tokens']))
    out['text'] = ' • '.join(parts) if parts else ''
    return out

def _v(_Lb) -> str:
    try:
        _Lb = int(_Lb)
    except Exception:
        return str(_Lb)
    if _Lb >= 1000000000:
        return '%.2f млрд токенов' % (_Lb / 1000000000)
    if _Lb >= 1000000:
        return '%.2f млн токенов' % (_Lb / 1000000)
    if _Lb >= 1000:
        return '%.1f тыс. токенов' % (_Lb / 1000)
    return '%d токенов' % _Lb

def _w(_Lb: str, _Lc: str) -> list:
    _Ln = _q(_Lb)
    if not _Ln:
        raise ValueError('Не задан URL провайдера')
    _Lm = []
    if re.search('/v\\d+[a-z]?$', _Ln, re.I):
        _Lm.append(_Ln + '/models')
    else:
        _Lm += [_Ln + '/v1/models', _Ln + '/models']
    _Le = None
    for _Ld in _Lm:
        try:
            _Lk, _Ll = _r(_Ld, _Lc)
        except Exception as _Lj:
            _Le = _Lj
            continue
        if _Lk == 404:
            continue
        if _Lk in (401, 403):
            raise PermissionError('Сервер отклонил ключ (HTTP %s)' % _Lk)
        if _Lk >= 400:
            raise RuntimeError('HTTP %s при запросе %s' % (_Lk, _Ld))
        _Li = _Ll.get('data') or _Ll.get('models') or [] if isinstance(_Ll, dict) else _Ll
        _Lh = []
        for _Lf in _Li or []:
            if isinstance(_Lf, str):
                _Lf = {'id': _Lf}
            if not isinstance(_Lf, dict):
                continue
            _Lg = _Lf.get('id') or _Lf.get('name')
            if not _Lg:
                continue
            _Lh.append({'id': str(_Lg), 'display': _Lf.get('display_name') or _Lf.get('name') or str(_Lg), 'context': _Lf.get('context_window') or _Lf.get('contextWindow') or _Lf.get('context_length') or _Lf.get('max_context_tokens'), 'output': _Lf.get('max_output_tokens') or _Lf.get('max_tokens'), 'tools': _Lf.get('supports_tools'), 'vision': _Lf.get('supports_vision')})
        if _Lh:
            return sorted(_Lh, key=lambda m: m['display'].lower())
        _Le = RuntimeError('Сервер вернул пустой список моделей')
    if isinstance(_Le, Exception):
        raise _Le
    raise RuntimeError('Не удалось получить список моделей')

def _x(_Lb: dict) -> list:
    _Ln = _Lb.get('providers')
    _Lm = []
    if not isinstance(_Ln, dict):
        return _Lm
    for _Lc, _Ld in _Ln.items():
        _Ld = _Ld if isinstance(_Ld, dict) else {}
        _Ll = _Ld.get('settings') if isinstance(_Ld.get('settings'), dict) else {}
        _Lk = _Ld.get('models') if isinstance(_Ld.get('models'), dict) else {}
        _Li, _Lj = ([], [])
        for _Lg, _Lh in _Lk.items():
            _Lj.append(_Lg)
            if isinstance(_Lh, dict) and _Lh.get('disabled'):
                continue
            _Li.append(_Lg)
        for _Lg in _Lj:
            if _Lg not in _Li:
                continue
        _Lm.append({'id': _Lc, 'display_name': _Ld.get('name') or _Lc, 'coefficient': str(_Ld.get('_coefficient') or ''), 'base_url': _Ll.get('baseURL') or '', 'api_key': _Ll.get('apiKey') or '', 'package': _Ld.get('package') or PACKAGES[0], 'models': _Li, 'known_models': _Lj, 'extra_settings': {_Le: _Lf for _Le, _Lf in _Ll.items() if _Le not in ('baseURL', 'apiKey')}, '_raw': copy.deepcopy(_Ld)})
    return _Lm

def _y(_Lb: dict) -> str:
    _Le = _Lb.get('model')
    if isinstance(_Le, str):
        return _Le
    if isinstance(_Le, dict):
        _Ld = _Le.get('providerID') or ''
        _Lc = _Le.get('model') or _Le.get('modelID') or ''
        if _Ld and _Lc:
            return '%s/%s' % (_Ld, _Lc)
    return ''

def _z(_Lb: str):
    _Lb = (_Lb or '').strip()
    if '/' not in _Lb:
        return ('', '')
    _Lc, _Ld = _Lb.split('/', 1)
    return (_Lc.strip(), _Ld.strip())

def _0(_Lb: dict, _Lc=None) -> dict:
    _Lf = copy.deepcopy(_Lc) if isinstance(_Lc, dict) else {}
    _Lf.pop('disabled', None)
    _Lf.setdefault('name', _Lb.get('display') or _Lb['id'])
    _Le = _Lf.get('limit') if isinstance(_Lf.get('limit'), dict) else {}
    if _Lb.get('context'):
        _Le['context'] = int(_Lb['context'])
    if _Lb.get('output'):
        _Le['output'] = int(_Lb['output'])
    if _Le:
        _Lf['limit'] = _Le
    _Ld = _Lf.get('capabilities') if isinstance(_Lf.get('capabilities'), dict) else {}
    if _Lb.get('tools') is not None:
        _Ld['tools'] = bool(_Lb['tools'])
    _Ld.setdefault('tools', True)
    if _Lb.get('vision'):
        _Ld['input'] = ['text', 'image']
    _Ld.setdefault('input', ['text'])
    _Ld.setdefault('output', ['text'])
    _Lf['capabilities'] = _Ld
    return _Lf

def _1(_Lb):
    if isinstance(_Lb, dict):
        return {_Ld: _1(_Lc) for _Ld, _Lc in _Lb.items() if not _Ld.startswith('_')}
    if isinstance(_Lb, list):
        return [_1(_Lc) for _Lc in _Lb]
    return _Lb

def _2(_Lb: dict, _Lc: str) -> str:
    _Lf = _Lb.get('providers') or {}
    _Le = _Lf.get(_Lc) or {}
    _Ld = _Le.get('_coefficient')
    if _Ld in (None, ''):
        return ''
    return str(_Ld)

def _3(_Lb: dict) -> dict:
    _Lm = {}
    _Ll = _q(_Lb.get('base_url', ''))
    if _Ll:
        _Lm['baseURL'] = _Ll
    if _Lb.get('api_key'):
        _Lm['apiKey'] = _Lb['api_key']
    for _Lj, _Lk in (_Lb.get('extra_settings') or {}).items():
        _Lm[_Lj] = _Lk
    _Li = copy.deepcopy(_Lb.get('_raw') or {})
    _Lh = str(_Lb.get('coefficient') or '').strip()
    if _Lh:
        _Li['_coefficient'] = _Lh
    else:
        _Li.pop('_coefficient', None)
    _Li['name'] = _Lb.get('display_name') or _Lb.get('id')
    _Li['package'] = _Lb.get('package') or PACKAGES[0]
    if _Lm:
        _Li['settings'] = _Lm
    else:
        _Li.pop('settings', None)
    _Lg = _Li.get('models') if isinstance(_Li.get('models'), dict) else {}
    _Lf = {}
    for _Lc in _Lb.get('models') or []:
        _Lf[_Lc] = _0({'id': _Lc}, _Lg.get(_Lc))
    for _Lc, _Ld in _Lg.items():
        if _Lc in _Lf:
            continue
        _Le = copy.deepcopy(_Ld) if isinstance(_Ld, dict) else {}
        _Le['disabled'] = True
        _Lf[_Lc] = _Le
    if _Lf:
        _Li['models'] = _Lf
    else:
        _Li.pop('models', None)
    return _Li

def _4(_Lb: dict, _Lc: list) -> dict:
    _Lg = copy.deepcopy(_Lb)
    if not isinstance(_Lg.get('providers'), dict):
        _Lg['providers'] = {}
    _Lg['providers'] = {_Lf['id']: _3(_Lf) for _Lf in _Lc}
    _Le = _y(_Lg)
    _Ld = _z(_Le)[0]
    if _Le and _Ld not in _Lg['providers']:
        _Lg.pop('model', None)
    return _Lg

class _5(tk.Toplevel):

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
        self.configure(bg=_b._T1)
        self.transient(app.root)
        self.grab_set()
        self.var_id = tk.StringVar(value=(profile or {}).get('id', ''))
        self.var_name = tk.StringVar(value=(profile or {}).get('display_name', ''))
        self.var_url = tk.StringVar(value=(profile or {}).get('base_url', ''))
        self.var_key = tk.StringVar(value=(profile or {}).get('api_key', ''))
        self.var_pkg = tk.StringVar(value=(profile or {}).get('package', PACKAGES[0]))
        self.var_set_default = tk.BooleanVar(value=False)
        self.var_coef = tk.StringVar(value=str((profile or {}).get('coefficient', '') or ''))
        self.var_filter = tk.StringVar()
        self.var_filter.trace_add('write', lambda *a: self._render_models())
        self._balance_value = (profile or {}).get('_balance') or None
        self.var_coef.trace_add('write', lambda *a: self._update_estimate())
        self._build()
        if self._balance_value:
            try:
                self.lbl_balance.configure(text=self._balance_value.get('text') or '—', fg=_b._T11)
                self.lbl_balance_src.configure(text=(self._balance_value.get('url') or '') + '  •  из последнего запроса')
            except Exception:
                pass
        try:
            app.clipboard.bind_tree(self)
        except Exception:
            pass
        self.bind('<Escape>', lambda e: self._cancel())
        if not self.is_new and self.known_models:
            for mid in self.known_models:
                self.models.append({'id': mid, 'display': mid})
            self._render_models()

    def _field(self, parent, row, label, var, show=None):
        tk.Label(parent, text=label, bg=_b._T1, fg=_b._T7, font=_b._T15, width=15, anchor='w').grid(row=row, column=0, sticky='w', padx=(4, 8), pady=4)
        ent = ttk.Entry(parent, textvariable=var, font=_b._T14)
        if show:
            ent.configure(show=show)
        ent.grid(row=row, column=1, sticky='ew', padx=6, pady=4)
        return ent

    def _build(self):
        head = tk.Frame(self, bg=_b._T1)
        head.pack(fill='x', padx=16, pady=(14, 2))
        tk.Label(head, text='ПРОФИЛЬ ПРОВАЙДЕРА', bg=_b._T1, fg=_b._T6, font=_b._T16).pack(anchor='w')
        _d(self, color=_b._T6).pack(fill='x', padx=16, pady=(4, 8))
        form = tk.Frame(self, bg=_b._T1)
        form.pack(fill='x', padx=16)
        self.e_id = self._field(form, 0, 'ID ПРОВАЙДЕРА', self.var_id)
        self._field(form, 1, 'НАЗВАНИЕ', self.var_name)
        self._field(form, 2, 'URL ПРОВАЙДЕРА', self.var_url)
        self.e_key = self._field(form, 3, 'API KEY', self.var_key, show='•')
        ttk.Button(form, text='ПОКАЗАТЬ', command=self._toggle_key).grid(row=3, column=2, padx=6)
        tk.Label(form, text='ТРАНСПОРТ', bg=_b._T1, fg=_b._T7, font=_b._T15, width=15, anchor='w').grid(row=4, column=0, sticky='w', padx=(4, 8), pady=4)
        ttk.Combobox(form, values=PACKAGES, textvariable=self.var_pkg, state='readonly', font=_b._T14, width=34).grid(row=4, column=1, sticky='w', padx=6, pady=4)
        tk.Label(form, text='КОЭФФИЦИЕНТ', bg=_b._T1, fg=_b._T7, font=_b._T15, width=15, anchor='w').grid(row=5, column=0, sticky='w', padx=(4, 8), pady=4)
        coef_row = tk.Frame(form, bg=_b._T1)
        coef_row.grid(row=5, column=1, sticky='w', padx=6, pady=4)
        ttk.Entry(coef_row, textvariable=self.var_coef, font=_b._T14, width=10).pack(side='left')
        tk.Label(coef_row, text='напр. 0.1 — множитель тарифа (лимит ÷ коэффициент = запас токенов)', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(side='left', padx=8)
        form.columnconfigure(1, weight=1)
        row = tk.Frame(self, bg=_b._T1)
        row.pack(fill='x', padx=16, pady=(10, 4))
        self.btn_check = ttk.Button(row, text='ПОЛУЧИТЬ СПИСОК МОДЕЛЕЙ', style='Accent.TButton', command=self._check_key)
        self.btn_check.pack(side='left', padx=(4, 6), pady=4)
        self.btn_balance = ttk.Button(row, text='ЗАПРОСИТЬ БАЛАНС', command=self._check_balance)
        self.btn_balance.pack(side='left', padx=(0, 10), pady=4)
        self.lbl_status = tk.Label(row, text='ВВЕДИТЕ URL И КЛЮЧ, ЗАТЕМ ЗАПРОСИТЕ МОДЕЛИ', bg=_b._T1, fg=_b._T7, font=_b._T15)
        self.lbl_status.pack(side='left', padx=4)
        bal_row = tk.Frame(self, bg=_b._T1)
        bal_row.pack(fill='x', padx=16, pady=(0, 4))
        tk.Label(bal_row, text='БАЛАНС', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(side='left', padx=(6, 10))
        self.lbl_balance = tk.Label(bal_row, text='—', bg=_b._T1, fg=_b._T9, font=_b._T17 if hasattr(_b, 'mono_big') else _b._T16)
        self.lbl_balance.pack(side='left', padx=4)
        self.lbl_balance_src = tk.Label(bal_row, text='', bg=_b._T1, fg=_b._T8, font=_b._T15)
        self.lbl_balance_src.pack(side='left', padx=10)
        self.lbl_balance_est = tk.Label(self, text='', bg=_b._T1, fg=_b._T7, font=_b._T15, anchor='w')
        self.lbl_balance_est.pack(fill='x', padx=18, pady=(0, 2))
        _d(self, color=_b._T9).pack(fill='x', padx=16, pady=(6, 6))
        mid = tk.Frame(self, bg=_b._T1)
        mid.pack(side='bottom', fill='both', expand=True, padx=16)
        mid.pack_propagate(False)
        mhead = tk.Frame(mid, bg=_b._T1)
        mhead.pack(fill='x')
        tk.Label(mhead, text='ДОСТУПНЫЕ МОДЕЛИ', bg=_b._T1, fg=_b._T6, font=_b._T16).pack(side='left', padx=2)
        ttk.Button(mhead, text='☑ ВСЕ', width=8, style='Accent.TButton', command=lambda: self._set_all(True)).pack(side='right', padx=3)
        ttk.Button(mhead, text='☐ НИЧЕГО', width=10, style='Accent.TButton', command=lambda: self._set_all(False)).pack(side='right', padx=3)
        self.lbl_selected = tk.Label(mhead, text='ОТМЕЧЕНО: 0 / 0', bg=_b._T1, fg=_b._T9, font=_b._T15)
        self.lbl_selected.pack(side='right', padx=10)
        khint = tk.Frame(mid, bg=_b._T1)
        khint.pack(fill='x', pady=(2, 0))
        tk.Label(khint, text='SHIFT+КЛИК — ИНВЕРСИЯ   •   CTRL+КЛИК — ВКЛ/ВЫКЛ ВСЁ', bg=_b._T1, fg=_b._T7, font=_b._T15).pack(anchor='w', padx=2)
        srow = tk.Frame(mid, bg=_b._T1)
        srow.pack(fill='x', pady=(6, 4))
        tk.Label(srow, text='ФИЛЬТР', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(side='left', padx=(2, 8))
        ttk.Entry(srow, textvariable=self.var_filter, font=_b._T14).pack(side='left', fill='x', expand=True, padx=(0, 4))
        box = tk.Frame(mid, bg=_b._T1, highlightthickness=1, highlightbackground=_b._T5)
        box.pack(side='bottom', fill='both', expand=True, pady=(0, 6))
        self.canvas = tk.Canvas(box, bg=_b._T2, highlightthickness=0)
        sb = ttk.Scrollbar(box, orient='vertical', command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=_b._T2)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.configure(yscrollcommand=sb.set)
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))
        self.canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.canvas.bind('<Enter>', self._bind_wheel)
        self.canvas.bind('<Leave>', self._unbind_wheel)
        bottom = tk.Frame(self, bg=_b._T1)
        bottom.pack(side='bottom', fill='x', padx=16, pady=(4, 14))
        tk.Checkbutton(bottom, text='МОДЕЛЬ ПО УМОЛЧАНИЮ', variable=self.var_set_default, bg=_b._T1, fg=_b._T12, selectcolor=_b._T4, activebackground=_b._T1, activeforeground=_b._T6, font=_b._T15, bd=0).pack(side='left', padx=4)
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
            tk.Label(self.inner, text='МОДЕЛЕЙ ПОКА НЕТ — ПРОВЕРЬТЕ URL/КЛЮЧ', bg=_b._T2, fg=_b._T13, font=_b._T15).pack(anchor='w', padx=10, pady=10)
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
            cb = _8(self.inner, self, self.model_vars[mid], text)
            cb.var = self.model_vars[mid]
            cb.pack(anchor='w', padx=8, pady=1, fill='x')
        if shown == 0:
            tk.Label(self.inner, text='ПО ФИЛЬТРУ НИЧЕГО НЕ НАЙДЕНО', bg=_b._T2, fg=_b._T13, font=_b._T15).pack(anchor='w', padx=10, pady=10)

    def _check_key(self):
        base, key = (self.var_url.get(), self.var_key.get())
        if not base.strip():
            messagebox.showwarning('Проверка', 'Сначала введите URL провайдера', parent=self)
            return
        self.btn_check.configure(state='disabled')
        self.lbl_status.configure(text='ПРОВЕРЯЕМ…')

        def work():
            try:
                self._results.put((_w(base, key), None))
            except Exception as _Lb:
                self._results.put((None, _Lb))
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
        self.lbl_balance.configure(text='…', fg=_b._T13)
        self.lbl_balance_src.configure(text='запрашиваю')

        def work():
            try:
                self._results.put(('balance', _t(base, key), None))
            except Exception as _Lb:
                self._results.put(('balance', None, _Lb))
        threading.Thread(target=work, daemon=True).start()
        self._poll_results()

    def _on_balance(self, data, err):
        try:
            self.btn_balance.configure(state='normal')
        except Exception:
            pass
        if err is not None:
            self.lbl_balance.configure(text='—', fg=_b._T10)
            self.lbl_balance_src.configure(text=str(err)[:90])
            return
        text = data.get('text') or '—'
        self.lbl_balance.configure(text=text, fg=_b._T11)
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
            est = _s(units, coef_txt)
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
        base = _q(self.var_url.get())
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

class _6(tk.Toplevel):

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title('ИСТОРИЯ КОНФИГА И ОТКАТ')
        self.geometry('920x620')
        self.minsize(780, 430)
        self.configure(bg=_b._T1)
        self.transient(app.root)
        self.grab_set()
        head = tk.Frame(self, bg=_b._T1)
        head.pack(fill='x', padx=16, pady=(14, 2))
        tk.Label(head, text='ИСТОРИЯ ВЕРСИЙ', bg=_b._T1, fg=_b._T6, font=_b._T16).pack(side='left', padx=2)
        ttk.Button(head, text='СНИМОК СЕЙЧАС', command=self.make_now).pack(side='right', padx=4)
        ttk.Button(head, text='ОБНОВИТЬ', command=self.reload).pack(side='right', padx=4)
        _d(self, color=_b._T6).pack(fill='x', padx=16, pady=(4, 8))
        foot = tk.Frame(self, bg=_b._T1)
        foot.pack(side='bottom', fill='x', padx=16, pady=(4, 14))
        tk.Label(foot, text='ОТКАТ ВОССТАНАВЛИВАЕТ ФАЙЛ ЦЕЛИКОМ', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(side='left', padx=4)
        ttk.Button(foot, text='ЗАКРЫТЬ', command=self.destroy).pack(side='right', padx=4)
        ttk.Button(foot, text='ВОССТАНОВИТЬ ВЫБРАННОЕ', style='Accent.TButton', command=self.restore_selected).pack(side='right', padx=4)
        prev = tk.Frame(self, bg=_b._T1)
        prev.pack(side='bottom', fill='x', padx=16, pady=(8, 4))
        tk.Label(prev, text='СОДЕРЖИМОЕ СНИМКА', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(anchor='w')
        self.preview_box = tk.Text(prev, height=7, bg=_b._T4, fg=_b._T12, relief='flat', font=_b._T15, insertbackground=_b._T6, wrap='none', highlightthickness=1, highlightbackground=_b._T5)
        self.preview_box.pack(fill='both', expand=True, pady=4)
        mid = tk.Frame(self, bg=_b._T1, highlightthickness=1, highlightbackground=_b._T5)
        mid.pack(fill='both', expand=True, padx=16)
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
        self.items = _l(self.app.config_path)
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

class _7:
    pass

class _8(tk.Checkbutton):

    def __init__(self, master, owner, variable, text, **kw):
        kw.setdefault('bg', _b._T2)
        kw.setdefault('fg', _b._T12)
        kw.setdefault('selectcolor', _b._T4)
        kw.setdefault('activebackground', _b._T2)
        kw.setdefault('activeforeground', _b._T6)
        kw.setdefault('font', _b._T15)
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

class _9:

    def __init__(self, _Lb):
        self.root = _Lb
        self.menu = tk.Menu(_Lb, tearoff=0, bg=_b._T3, fg=_b._T12, activebackground='#0b3547', activeforeground=_b._T6, font=_b._T15, bd=0, relief='flat')
        self.menu.add_command(label='ВЫРЕЗАТЬ        Ctrl+X', command=self._cut)
        self.menu.add_command(label='КОПИРОВАТЬ      Ctrl+C', command=self._copy)
        self.menu.add_command(label='ВСТАВИТЬ        Ctrl+V', command=self._paste)
        self.menu.add_separator()
        self.menu.add_command(label='ВЫДЕЛИТЬ ВСЁ    Ctrl+A', command=self._select_all)
        self._target = None
        self._last_clip = ''
        self._watch_widget = None
        self._watch_after = None
        self._watch_armed = False
        self.menu.bind('<FocusOut>', lambda e: self.menu.unpost())

    def _widget(self, _Lb):
        _Lc = _Lb.widget
        try:
            if _Lc.winfo_class() in ('TEntry', 'Entry', 'Text'):
                return _Lc
        except Exception:
            pass
        return None

    def bind(self, _Lb):
        _Lb.bind('<Button-3>', self.popup, add='+')
        return _Lb

    def bind_tree(self, _Lb):
        self.bind(_Lb)
        for _Lc in _Lb.winfo_children():
            self.bind_tree(_Lc)

    def _cls(self, _Lb):
        try:
            return _Lb.winfo_class()
        except Exception:
            return ''

    def _copy(self):
        _Lc = self._target
        if not _Lc:
            return
        try:
            if self._cls(_Lc) == 'Text':
                _Lb = _Lc.get('sel.first', 'sel.last') if _Lc.tag_ranges('sel') else _Lc.get('1.0', 'end-1c')
            else:
                _Lb = _Lc.selection_get()
        except Exception:
            _Lb = ''
        if _Lb:
            self.root.clipboard_clear()
            self.root.clipboard_append(_Lb)

    def _cut(self):
        _Lb = self._target
        if not _Lb:
            return
        self._copy()
        try:
            if self._cls(_Lb) == 'Text':
                if _Lb.tag_ranges('sel'):
                    _Lb.delete('sel.first', 'sel.last')
            else:
                _Lb.delete('sel.first', 'sel.last')
        except Exception:
            pass

    def _paste(self):
        _Lc = self._target
        if not _Lc:
            return
        _Lb = self._read_clip()
        if not _Lb:
            return
        self._insert_text(_Lc, _Lb)

    def _select_all(self):
        _Lb = self._target
        if not _Lb:
            return
        try:
            if self._cls(_Lb) == 'Text':
                _Lb.tag_add('sel', '1.0', 'end-1c')
            else:
                _Lb.selection_range(0, 'end')
                _Lb.icursor('end')
        except Exception:
            pass

    def _read_clip(self):
        try:
            return self.root.clipboard_get()
        except Exception:
            return ''

    def watch_begin(self, _Lb):
        self._watch_widget = _Lb
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
        _Ld = self._watch_widget
        try:
            _Lc = _Ld is not None and _Ld.winfo_exists()
        except Exception:
            _Lc = False
        if not _Lc:
            self._watch_armed = False
            return
        _Lb = self._read_clip()
        if _Lb and _Lb != self._last_clip:
            self._watch_armed = False
            self._watch_widget = None
            self._target = _Ld
            try:
                _Ld.icursor('end')
            except Exception:
                try:
                    _Ld.mark_set('insert', 'end')
                except Exception:
                    pass
            self._insert_text(_Ld, _Lb)
            try:
                _Ld.focus_force()
            except Exception:
                pass
            return
        self._watch_after = self.root.after(200, self._watch_tick)

    def _insert_text(self, _Lb, _Lc):
        try:
            if str(_Lb.cget('state')) == 'readonly':
                return
        except Exception:
            pass
        try:
            try:
                _Lb.delete('sel.first', 'sel.last')
            except Exception:
                pass
            _Lb.insert('insert', _Lc)
        except Exception:
            pass

    def popup(self, _Lb):
        _Lc = self._widget(_Lb)
        if _Lc is None:
            return 'break'
        self._target = _Lc
        self._last_clip = self._read_clip()
        try:
            self.menu.tk_popup(_Lb.x_root, _Lb.y_root)
        finally:
            self.menu.grab_release()
        return 'break'

def _aa(menu, root, interval=700):
    state = {'last': menu._read_clip(), 'skip': 0}

    def tick():
        try:
            _Le = menu._read_clip()
        except Exception:
            _Le = ''
        if _Le and _Le != state['last']:
            state['last'] = _Le
            _Ld = None
            try:
                _Ld = root.focus_get()
            except Exception:
                _Ld = None
            try:
                _Lc = _Ld is not None and _Ld.winfo_class() in ('TEntry', 'Entry', 'Text')
            except Exception:
                _Lc = False
            if _Lc and (not menu._watch_armed):
                _Lb = ''
                try:
                    _Lb = _Ld.get()
                except Exception:
                    pass
                if _Le not in (_Lb or ''):
                    menu._insert_text(_Ld, _Le)
                    state['skip'] = 2
        try:
            root.after(interval, tick)
        except Exception:
            pass
    root.after(interval, tick)

def _ab(root):
    menu = _9(root)

    def cur():
        try:
            return root.focus_get()
        except Exception:
            return None

    def do(action):

        def handler(_Lb=None):
            menu._target = cur()
            action()
            return 'break'
        return handler

    def bind_to(_Lb):
        try:
            if _Lb.winfo_class() in ('TEntry', 'Entry', 'Text'):
                for _Ld, _Le in (('<Control-c>', do(menu._copy)), ('<Control-v>', do(menu._paste)), ('<Control-x>', do(menu._cut)), ('<Control-a>', do(menu._select_all))):
                    _Lb.bind(_Ld, _Le, add='+')
        except Exception:
            pass
        for _Lc in _Lb.winfo_children():
            bind_to(_Lc)
    bind_to(root)
    for klass, seq, fn in (('TEntry', '<Control-c>', do(menu._copy)), ('TEntry', '<Control-v>', do(menu._paste)), ('TEntry', '<Control-x>', do(menu._cut)), ('TEntry', '<Control-a>', do(menu._select_all)), ('Text', '<Control-c>', do(menu._copy)), ('Text', '<Control-v>', do(menu._paste)), ('Text', '<Control-x>', do(menu._cut)), ('Text', '<Control-a>', do(menu._select_all))):
        try:
            root.bind_class(klass, seq, fn, add='+')
        except Exception:
            pass
    for seq, fn in (('<Control-c>', do(menu._copy)), ('<Control-v>', do(menu._paste)), ('<Control-x>', do(menu._cut)), ('<Control-a>', do(menu._select_all)), ('<Control-Insert>', do(menu._copy)), ('<Shift-Insert>', do(menu._paste))):
        try:
            root.bind_all(seq, fn, add='+')
        except Exception:
            pass

    def do_winv(_Lb=None):
        _Lc = cur()
        if _Lc is not None:
            menu.watch_begin(_Lc)
        return None
    for seq in ('<Control-KeyPress-v>', '<Shift-KeyPress-Insert>', '<Control-Insert>'):

        def arm(_Lb, _Lc=seq):
            _Ld = menu._widget(_Lb)
            if _Ld is not None:
                menu.watch_begin(_Ld)
            return None
        try:
            root.bind_all(seq, arm, add='+')
        except Exception:
            pass
    try:
        _aa(menu, root)
    except Exception:
        pass
    return menu

class App:

    def __init__(self):
        self.root_ready = True
        self.config_path = _h()
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
        self.root.configure(bg=_b._T1)
        _c(self.root)
        self.clipboard = _ab(self.root)
        self._build()
        try:
            self.clipboard.bind_tree(self.root)
        except Exception:
            pass
        self.root.bind('<Control-z>', lambda e: self.undo_last())
        self.root.bind('<Control-Z>', lambda e: self.undo_last())

    def _build(self):
        _L0 = self.root
        _Lz = tk.Frame(_L0, bg=_b._T1)
        _Lz.pack(fill='x', padx=16, pady=(14, 4))
        _Ly = tk.Frame(_Lz, bg=_b._T1)
        _Ly.pack(side='left', padx=(2, 20))
        tk.Label(_Ly, text='OPENCODE', bg=_b._T1, fg=_b._T6, font=_b._T17).pack(anchor='w')
        tk.Label(_Ly, text='ПРОВАЙДЕРЫ И МОДЕЛИ', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(anchor='w')
        _Lx = tk.Frame(_Lz, bg=_b._T1)
        _Lx.pack(side='left', fill='x', expand=True, padx=8)
        tk.Label(_Lx, text='КОНФИГУРАЦИЯ', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(anchor='w')
        self.var_path = tk.StringVar(value=str(self.config_path))
        ttk.Entry(_Lx, textvariable=self.var_path, font=_b._T14).pack(fill='x', pady=(2, 0))
        _Lw = tk.Frame(_Lz, bg=_b._T1)
        _Lw.pack(side='right', padx=(8, 2))
        ttk.Button(_Lw, text='ОТКРЫТЬ ПАПКУ', command=self._open_folder).pack(side='left', padx=3)
        ttk.Button(_Lw, text='ПЕРЕЗАГРУЗИТЬ', command=self.load).pack(side='left', padx=3)
        _d(_L0, color=_b._T6).pack(fill='x', padx=16, pady=(6, 0))
        _Lv = tk.Frame(_L0, bg=_b._T1)
        _Lv.pack(fill='both', expand=True, padx=16, pady=8)
        _Lu = tk.Frame(_Lv, bg=_b._T1, width=430, highlightthickness=1, highlightbackground=_b._T5)
        _Lu.pack(side='left', fill='y', padx=(0, 10))
        _Lu.pack_propagate(False)
        _Lt = tk.Frame(_Lu, bg=_b._T2)
        _Lt.pack(fill='x', padx=10, pady=(10, 6))
        tk.Label(_Lt, text='ПРОФИЛИ', bg=_b._T2, fg=_b._T6, font=_b._T16).pack(side='left')
        self.lbl_count = tk.Label(_Lt, text='0', bg=_b._T2, fg=_b._T13, font=_b._T15)
        self.lbl_count.pack(side='right')
        _Ls = tk.Frame(_Lu, bg=_b._T2)
        _Ls.pack(fill='both', expand=True, padx=8, pady=4)
        self.tree = ttk.Treeview(_Ls, columns=('name', 'url'), show='headings', selectmode='browse')
        self.tree.heading('name', text='ПРОФИЛЬ')
        self.tree.heading('url', text='URL')
        self.tree.column('name', width=150, anchor='w')
        self.tree.column('url', width=245, anchor='w')
        _Lr = ttk.Scrollbar(_Ls, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=_Lr.set)
        self.tree.pack(side='left', fill='both', expand=True)
        _Lr.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._on_select())
        self.tree.bind('<Double-1>', lambda e: self.edit_profile())
        _Lq = tk.Frame(_Lu, bg=_b._T2)
        _Lq.pack(fill='x', padx=8, pady=(6, 10))
        ttk.Button(_Lq, text='+ ДОБАВИТЬ', style='Accent.TButton', command=self.add_profile).pack(side='left', padx=(2, 3), pady=4)
        ttk.Button(_Lq, text='ИЗМЕНИТЬ', command=self.edit_profile).pack(side='left', padx=3)
        ttk.Button(_Lq, text='УДАЛИТЬ', style='Danger.TButton', command=self.delete_profile).pack(side='left', padx=3)
        _Lp = tk.Frame(_Lv, bg=_b._T1, highlightthickness=1, highlightbackground=_b._T5)
        _Lp.pack(side='left', fill='both', expand=True)
        _Lo = tk.Frame(_Lp, bg=_b._T2)
        _Lo.pack(fill='x', padx=12, pady=(10, 2))
        tk.Label(_Lo, text='ПРОФИЛЬ', bg=_b._T2, fg=_b._T13, font=_b._T15).pack(anchor='w')
        self.lbl_title = tk.Label(_Lo, text='— НЕ ВЫБРАН —', bg=_b._T2, fg=_b._T6, font=_b._T17)
        self.lbl_title.pack(anchor='w', pady=(2, 0))
        _Ln = tk.Frame(_Lp, bg=_b._T2)
        _Ln.pack(fill='x', padx=10, pady=(8, 4))
        self.detail_vars = {}
        for _Lj, (_Lk, _Ll) in enumerate([('ID', 'id'), ('НАЗВАНИЕ', 'display_name'), ('URL', 'base_url'), ('API KEY', 'api_key'), ('ТРАНСПОРТ', 'package')]):
            tk.Label(_Ln, text=_Lk, bg=_b._T2, fg=_b._T13, font=_b._T15, width=11, anchor='w').grid(row=_Lj, column=0, sticky='w', padx=(6, 8), pady=3)
            _Lm = tk.StringVar()
            self.detail_vars[_Ll] = _Lm
            _Ld = ttk.Entry(_Ln, textvariable=_Lm, font=_b._T14)
            _Ld.grid(row=_Lj, column=1, sticky='ew', padx=6, pady=3)
            _Ld.configure(state='readonly')
            if _Ll == 'api_key':
                _Ld.configure(show='•')
                ttk.Button(_Ln, text='ПОКАЗАТЬ', command=lambda e=_Ld: self._toggle_entry(e)).grid(row=_Lj, column=2, padx=6)
        _Ln.columnconfigure(1, weight=1)
        _Li = tk.Frame(_Lp, bg=_b._T2)
        _Li.pack(fill='x', padx=12, pady=(10, 0))
        tk.Label(_Li, text='БАЛАНС', bg=_b._T2, fg=_b._T13, font=_b._T15).pack(side='left')
        self.lbl_balance_main = tk.Label(_Li, text='—', bg=_b._T2, fg=_b._T13, font=_b._T14)
        self.lbl_balance_main.pack(side='left', padx=(10, 8))
        self.btn_balance_main = ttk.Button(_Li, text='ОБНОВИТЬ', command=self.request_balance)
        self.btn_balance_main.pack(side='right', padx=2)
        self.lbl_balance_when = tk.Label(_Li, text='', bg=_b._T2, fg=_b._T8, font=_b._T15)
        self.lbl_balance_when.pack(side='right', padx=8)
        self.lbl_balance_est_main = tk.Label(_Lp, text='', bg=_b._T2, fg=_b._T7, font=_b._T15, anchor='w')
        self.lbl_balance_est_main.pack(fill='x', padx=18, pady=(1, 0))
        _Lh = tk.Frame(_Lp, bg=_b._T2)
        _Lh.pack(fill='x', padx=12, pady=(10, 2))
        tk.Label(_Lh, text='МОДЕЛИ ПРОФИЛЯ', bg=_b._T2, fg=_b._T13, font=_b._T15).pack(side='left')
        self.lbl_models_count = tk.Label(_Lh, text='', bg=_b._T2, fg=_b._T9, font=_b._T15)
        self.lbl_models_count.pack(side='right')
        self.lst_models = tk.Listbox(_Lp, height=4, bg=_b._T4, fg=_b._T7, selectbackground='#0b3547', selectforeground=_b._T6, relief='flat', font=_b._T15, highlightthickness=1, highlightbackground=_b._T5)
        self.lst_models.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        self.lst_models.bind('<Double-1>', lambda e: self.make_default())
        self.lst_models.bind('<Return>', lambda e: self.make_default())
        _Lg = tk.Frame(_Lp, bg=_b._T2)
        _Lg.pack(fill='x', padx=12, pady=(0, 6))
        ttk.Button(_Lg, text='ИЗМЕНИТЬ ПРОФИЛЬ…', style='Accent.TButton', command=self.edit_profile).pack(side='left', fill='x', expand=True, padx=(2, 4), pady=4)
        ttk.Button(_Lg, text='ПО УМОЛЧАНИЮ', command=self.make_default).pack(side='left', fill='x', expand=True, padx=(4, 2), pady=4)
        _d(_L0, color=_b._T9).pack(fill='x', padx=16, pady=(2, 0))
        _Lf = tk.Frame(_L0, bg=_b._T1)
        _Lf.pack(fill='x', padx=16, pady=(8, 6))
        _Le = tk.Frame(_Lf, bg=_b._T1)
        _Le.pack(fill='x')
        tk.Label(_Le, text='МОДЕЛЬ ПО УМОЛЧАНИЮ', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(side='left', padx=(4, 10))
        self.var_default_model = tk.StringVar()
        _Ld = ttk.Entry(_Le, textvariable=self.var_default_model, font=_b._T14)
        _Ld.configure(state='readonly')
        _Ld.pack(side='left', fill='x', expand=True, padx=4, pady=4)
        ttk.Button(_Le, text='ПРИМЕНИТЬ К КОНФИГУ', style='Accent.TButton', command=self.write_config).pack(side='left', padx=(8, 4))
        self.lbl_dirty = tk.Label(_Le, text='', bg=_b._T1, fg=_b._T9, font=_b._T15)
        self.lbl_dirty.pack(side='left', padx=(6, 2))
        _Lc = tk.Frame(_Lf, bg=_b._T1)
        _Lc.pack(fill='x', pady=(6, 0))
        ttk.Button(_Lc, text='ИСТОРИЯ И ОТКАТ…', command=self.open_history).pack(side='left', padx=3)
        ttk.Button(_Lc, text='СНИМОК СЕЙЧАС', command=lambda: self.snapshot_now('Ручной снимок')).pack(side='left', padx=3)
        ttk.Button(_Lc, text='ЭКСПОРТ ПРОФИЛЯ…', command=self.export_profile).pack(side='left', padx=3)
        ttk.Button(_Lc, text='ИМПОРТ ПРОФИЛЯ…', command=self.import_profile).pack(side='left', padx=3)
        self.hist_info = tk.Label(_Lc, text='Снимков: 0', bg=_b._T1, fg=_b._T7, font=_b._T15, anchor='e')
        self.hist_info.pack(side='right', padx=(6, 10))
        tk.Frame(_Lc, bg=_b._T1).pack(side='left', fill='x', expand=True)
        tk.Label(_L0, text='CTRL+Z — ОТКАТ К ПРЕДЫДУЩЕЙ ВЕРСИИ', bg=_b._T1, fg=_b._T8, font=_b._T15).pack(anchor='w', padx=22, pady=(0, 2))
        _Lb = tk.Frame(_L0, bg=_b._T3, height=26)
        _Lb.pack(fill='x', side='bottom')
        _Lb.pack_propagate(False)
        self.status = tk.Label(_Lb, text='', bg=_b._T3, fg=_b._T7, font=_b._T15, anchor='w')
        self.status.pack(side='left', fill='x', expand=True, padx=14)

    def _toggle_entry(self, _Lb):
        _Lc = _Lb.cget('show') == ''
        _Lb.configure(show='•' if _Lc else '')

    def load(self):
        _Lc = Path(self.var_path.get().strip() or _h())
        self.config_path = _Lc
        try:
            self.config = _j(_Lc)
            self.profiles = _x(self.config)
        except Exception as _Lb:
            messagebox.showerror('Чтение конфига', 'Не удалось прочитать:\n%s\n\n%s' % (_Lc, _Lb))
            self.config, self.profiles = ({}, [])
        self.var_default_model.set(_y(self.config) or '(не задана)')
        self._render_list()
        self._refresh_history()
        self._base_signature = self._signature()
        self._set_status('ЗАГРУЖЕНО ПРОФИЛЕЙ: %d   •   %s' % (len(self.profiles), _Lc))

    def _signature(self) -> str:
        try:
            return json.dumps([self.config, self.profiles], sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return ''

    def _is_dirty(self) -> bool:
        return self._base_signature != self._signature()

    def _refresh_dirty_marker(self):
        _Lb = getattr(self, 'lbl_dirty', None)
        if _Lb is None:
            return
        try:
            _Lb.configure(text='● ЕСТЬ НЕСОХРАНЁННЫЕ ИЗМЕНЕНИЯ' if self._is_dirty() else '')
        except Exception:
            pass

    def _set_status(self, _Lb):
        try:
            self.status.configure(text=_Lb)
        except Exception:
            pass

    def _render_list(self):
        self.tree.delete(*self.tree.get_children())
        for _Lb in self.profiles:
            self.tree.insert('', 'end', iid=_Lb['id'], values=(_Lb['display_name'], _Lb['base_url']))
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

    def _find(self, _Lb):
        for _Lc in self.profiles:
            if _Lc['id'] == _Lb:
                return _Lc
        return None

    def _on_select(self):
        _Li = self.tree.selection()
        if not _Li:
            self._clear_details()
            return
        self.selected = _Li[0]
        _Lh = self._find(self.selected)
        if not _Lh:
            return
        self.lbl_title.configure(text=(_Lh['display_name'] or _Lh['id']).upper())
        for _Lg in ('id', 'display_name', 'base_url', 'package'):
            self.detail_vars[_Lg].set(_Lh[_Lg])
        _Lg = _Lh['api_key']
        self.detail_vars['api_key'].set('(не задан)' if not _Lg else _Lg[:6] + '…' + _Lg[-4:] if len(_Lg) > 12 else '••••')
        self.lst_models.delete(0, 'end')
        for _Lf in _Lh['models']:
            self.lst_models.insert('end', _Lf)
        if _Lh['models']:
            _Le = self.var_default_model.get()
            _Ld = str(_Lh['id']) + '/'
            _Lb = 0
            if _Le.startswith(_Ld):
                _Lc = _Le[len(_Ld):]
                if _Lc in _Lh['models']:
                    _Lb = _Lh['models'].index(_Lc)
            self.lst_models.selection_set(_Lb)
            self.lst_models.see(_Lb)
        else:
            self.lst_models.insert('end', '(модели не выбраны)')
        try:
            self.lbl_models_count.configure(text=str(len(_Lh['models'])))
            self.lst_models.configure(height=max(3, min(10, len(_Lh['models']) or 3)))
        except Exception:
            pass
        self._show_balance(_Lh)
        if not _Lh.get('_balance') and (not _Lh.get('_balance_tried')):
            _Lh['_balance_tried'] = True
            self.root.after(250, self.request_balance)

    def _clear_details(self):
        self.lbl_title.configure(text='— НЕ ВЫБРАН —')
        for _Lb in self.detail_vars.values():
            _Lb.set('')
        self.lst_models.delete(0, 'end')

    def add_profile(self):
        _Lc = _5(self, None)
        self.root.wait_window(_Lc)
        _Lb = _Lc.result
        if not _Lb:
            return
        self.profiles.append(self._from_dialog(_Lb))
        self._render_list()
        self.tree.selection_set(_Lb['id'])
        self._set_status('ДОБАВЛЕН ПРОФИЛЬ %s (НЕ СОХРАНЁН)' % _Lb['id'])
        self._refresh_dirty_marker()
        if _Lb.get('set_default') and _Lb['models']:
            self.var_default_model.set('%s/%s' % (_Lb['id'], _Lb['models'][0]))

    def edit_profile(self):
        if not self.selected:
            messagebox.showinfo('Изменить', 'Выберите профиль в списке', parent=self.root)
            return
        _Le = self._find(self.selected)
        if not _Le:
            return
        _Ld = _5(self, _Le)
        self.root.wait_window(_Ld)
        _Lc = _Ld.result
        if not _Lc:
            return
        _Lb = self.profiles.index(_Le)
        self.profiles[_Lb] = self._from_dialog(_Lc)
        self.selected = _Lc['id']
        self._render_list()
        self._set_status('ПРОФИЛЬ %s ОБНОВЛЁН (НЕ СОХРАНЁН)' % _Lc['id'])
        self._refresh_dirty_marker()

    def _from_dialog(self, _Lb):
        return {'id': _Lb['id'], 'display_name': _Lb['display_name'], 'base_url': _Lb['base_url'], 'api_key': _Lb['api_key'], 'package': _Lb['package'], 'models': list(_Lb['models']), 'known_models': list(_Lb['known_models']), 'coefficient': _Lb.get('coefficient') or '', 'extra_settings': _Lb.get('extra_settings') or {}, '_raw': _Lb.get('_raw')}

    def delete_profile(self):
        _Lb = self._find(self.selected) if self.selected else None
        if not _Lb:
            messagebox.showinfo('Удалить', 'Выберите профиль в списке', parent=self.root)
            return
        if not messagebox.askyesno('Удалить профиль', 'Удалить профиль «%s»?\n\nИз конфига он исчезнет после «ПРИМЕНИТЬ К КОНФИГУ».' % _Lb['display_name'], parent=self.root):
            return
        self.profiles.remove(_Lb)
        self.selected = None
        self._render_list()
        self._set_status('ПРОФИЛЬ %s УДАЛЁН ИЗ СПИСКА' % _Lb['id'])
        self._refresh_dirty_marker()

    def make_default(self):
        _Lc = self._find(self.selected) if self.selected else None
        if not _Lc or not _Lc['models']:
            messagebox.showinfo('По умолчанию', 'У выбранного профиля нет моделей', parent=self.root)
            return
        _Lb = self._selected_model()
        if not _Lb:
            if len(_Lc['models']) == 1:
                _Lb = _Lc['models'][0]
            else:
                _Lb = self._ask_model(_Lc)
                if not _Lb:
                    return
        self._apply_default(_Lc, _Lb)

    def _selected_model(self):
        try:
            _Lc = self.lst_models.curselection()
            if _Lc:
                _Lb = self.lst_models.get(_Lc[0])
                if _Lb and _Lb != '(модели не выбраны)':
                    return _Lb
        except Exception:
            pass
        return None

    def _apply_default(self, _Lb, _Lc):
        self.var_default_model.set('%s/%s' % (_Lb['id'], _Lc))
        self._set_status('МОДЕЛЬ ПО УМОЛЧАНИЮ: %s/%s (НЕ СОХРАНЕНО)' % (_Lb['id'], _Lc))
        self._refresh_dirty_marker()

    def _ask_model(self, profile):
        win = tk.Toplevel(self.root)
        win.title('МОДЕЛЬ ПО УМОЛЧАНИЮ')
        win.configure(bg=_b._T1)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text='ВЫБЕРИТЕ МОДЕЛЬ', bg=_b._T1, fg=_b._T6, font=_b._T16).pack(anchor='w', padx=14, pady=(12, 6))
        lb = tk.Listbox(win, height=min(12, len(profile['models'])), width=62, bg=_b._T2, fg=_b._T12, selectbackground='#0b3547', selectforeground=_b._T6, font=_b._T15, relief='flat', highlightthickness=1, highlightbackground=_b._T5)
        for mid in profile['models']:
            lb.insert('end', mid)
        lb.pack(fill='both', expand=True, padx=14, pady=4)
        lb.selection_set(0)
        chosen = {'value': None}

        def ok():
            _Lb = lb.curselection()
            if _Lb:
                chosen['value'] = profile['models'][_Lb[0]]
            win.destroy()
        row = tk.Frame(win, bg=_b._T1)
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
        self.lbl_balance_main.configure(text='ЗАГРУЗКА…', fg=_b._T13)
        self.lbl_balance_when.configure(text='запрос…')
        try:
            self.btn_balance_main.configure(state='disabled')
        except Exception:
            pass

        def work():
            try:
                self._balance_results.put((profile['id'], _t(profile['base_url'], profile['api_key']), None))
            except Exception as _Lb:
                self._balance_results.put((profile['id'], None, _Lb))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(120, self._poll_balance)

    def _poll_balance(self):
        try:
            _Lc, _Ld, _Le = self._balance_results.get_nowait()
        except queue.Empty:
            self.root.after(120, self._poll_balance)
            return
        try:
            self.btn_balance_main.configure(state='normal')
        except Exception:
            pass
        _Lb = self._find(_Lc)
        if _Lb is None:
            return
        if _Le is not None:
            self.lbl_balance_main.configure(text='нет данных', fg=_b._T10)
            self.lbl_balance_when.configure(text=str(_Le)[:70])
            _Lb['_balance'] = None
            _Lb['_balance_error'] = str(_Le)
            return
        _Lb['_balance'] = _Ld
        _Lb['_balance_error'] = None
        _Lb['_balance_at'] = datetime.now()
        if _Lc == self.selected:
            self._show_balance(_Lb)
        if not _Lb.get('_balance') and (not _Lb.get('_balance_tried')):
            _Lb['_balance_tried'] = True
            self.root.after(250, self.request_balance)

    def _show_balance(self, _Lb):
        _Lg = _Lb.get('_balance')
        _Lf = _Lb.get('_balance_at')
        try:
            if _Lg:
                self.lbl_balance_main.configure(text=_Lg.get('text') or '—', fg=_b._T11)
                self.lbl_balance_when.configure(text='обновлено %s' % _Lf.strftime('%H:%M:%S') if _Lf else '')
                _Le = str(_Lb.get('coefficient') or '').strip()
                _Ld = _s(_Lg.get('tokens'), _Le) if _Le else {}
                if _Ld:
                    self.lbl_balance_est_main.configure(text='≈ %s при коэффициенте %s' % (_Ld['text'], _Le))
                elif not _Le:
                    self.lbl_balance_est_main.configure(text='коэффициент не задан — укажите в профиле, чтобы видеть остаток в токенах')
                else:
                    self.lbl_balance_est_main.configure(text='')
            else:
                _Lc = _Lb.get('_balance_error')
                self.lbl_balance_main.configure(text='—' if not _Lc else 'нет данных', fg=_b._T13 if not _Lc else _b._T10)
                self.lbl_balance_when.configure(text=(_Lc or '')[:70])
                self.lbl_balance_est_main.configure(text='')
        except Exception:
            pass

    def _open_folder(self):
        try:
            os.startfile(str(self.config_path.parent))
        except Exception as _Lb:
            messagebox.showerror('Папка', str(_Lb), parent=self.root)

    def _refresh_history(self):
        try:
            self._history = _l(self.config_path)
        except Exception:
            self._history = []
        _Lc = getattr(self, 'hist_info', None)
        if _Lc is not None:
            _Lb = self._history[0]['time'].strftime('%d.%m.%Y %H:%M:%S') if self._history and self._history[0].get('time') else '—'
            _Lc.configure(text='Снимков: %d  •  последний: %s' % (len(self._history), _Lb))

    def open_history(self):
        _6(self)

    def snapshot_now(self, _Lb=''):
        try:
            _Ld = _m(self.config_path)
        except Exception as _Lc:
            messagebox.showerror('Снимок', str(_Lc), parent=self.root)
            return None
        if _Ld:
            self._refresh_history()
            self._set_status((_Lb + '  •  ' if _Lb else '') + 'СНИМОК: ' + _Ld.name)
        return _Ld

    def undo_last(self):
        if self._is_dirty():
            if not messagebox.askyesno('Откат', 'Есть неприменённые изменения в форме. Откатить файл к предыдущей версии?', parent=self.root):
                return
        self._refresh_history()
        if not self._history:
            messagebox.showinfo('Откат', 'Снимков ещё нет.', parent=self.root)
            return
        self.quick_restore(self._history[0])

    def quick_restore(self, _Lb):
        if not _Lb.get('valid'):
            messagebox.showerror('Откат', 'Снимок повреждён:\n%s' % _Lb['name'], parent=self.root)
            return
        _Le = _Lb['time'].strftime('%d.%m.%Y %H:%M:%S') if _Lb.get('time') else '?'
        if not messagebox.askyesno('Откатить конфиг?', 'Восстановить версию от %s?\n\nФайл: %s\nПровайдеры: %s\nМодель: %s\n\nТекущая версия тоже сохранится в историю.' % (_Le, _Lb['path'].name, ', '.join(_Lb.get('providers') or []) or '(нет)', _Lb.get('model') or '(не задана)'), parent=self.root):
            return
        try:
            _Ld = _p(self.config_path, _Lb['path'])
        except Exception as _Lc:
            messagebox.showerror('Откат', str(_Lc), parent=self.root)
            return
        self.load()
        self._set_status('ОТКАТ ВЫПОЛНЕН. ВЕРСИЯ ДО ОТКАТА: %s' % (_Ld.name if _Ld else '—'))
        messagebox.showinfo('Откат', 'Конфиг восстановлен из снимка %s.\nОткат самого отката: %s' % (_Lb['name'], _Ld.name if _Ld else '—'), parent=self.root)

    def write_config(self):
        _Lg = self._is_dirty()
        try:
            _Lf = _4(self.config, self.profiles)
            _Le = self.var_default_model.get().strip()
            if _Le and _Le != '(не задана)':
                _Lf['model'] = _Le
            _Ld = _o(self.config_path, _Lf)
        except Exception as _Lc:
            messagebox.showerror('Запись конфига', str(_Lc), parent=self.root)
            return
        self.config = _Lf
        self.profiles = _x(self.config)
        self._base_signature = self._signature()
        self._render_list()
        self._refresh_history()
        self._refresh_dirty_marker()
        _Lb = 'Конфиг записан. Предыдущая версия: %s' % (_Ld.name if _Ld else '—')
        self._set_status(_Lb.upper())
        messagebox.showinfo('Готово', '%s\n\nФайл: %s\n\nОткат: кнопка «ИСТОРИЯ И ОТКАТ…» или Ctrl+Z' % (_Lb, self.config_path), parent=self.root)
        if not _Lg:
            self._set_status('СОХРАНЕНА КОНТРОЛЬНАЯ ТОЧКА: ' + (_Ld.name if _Ld else '—'))

    def export_profile(self):
        _Le = self._find(self.selected) if self.selected else None
        if not _Le:
            messagebox.showinfo('Экспорт', 'Выберите профиль в списке', parent=self.root)
            return
        _Ld = {'version': 1, 'type': 'opencode-provider-profile', 'id': _Le['id'], 'display_name': _Le['display_name'], 'base_url': _Le['base_url'], 'package': _Le['package'], 'api_key': _Le['api_key'], 'models': list(_Le['models']), 'known_models': list(_Le['known_models']), 'extra_settings': _Le.get('extra_settings') or {}, 'raw': _Le.get('_raw') or {}}
        _Lc = filedialog.asksaveasfilename(parent=self.root, title='Экспорт профиля', defaultextension='.json', initialfile=_Le['id'] + '.profile.json', filetypes=[('Профиль OpenCode', '*.profile.json'), ('JSON', '*.json')])
        if not _Lc:
            return
        try:
            Path(_Lc).write_text(json.dumps(_Ld, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception as _Lb:
            messagebox.showerror('Экспорт', str(_Lb), parent=self.root)
            return
        self._set_status('ПРОФИЛЬ %s ЭКСПОРТИРОВАН: %s' % (_Le['id'], _Lc))

    def import_profile(self):
        _Lg = filedialog.askopenfilename(parent=self.root, title='Импорт профиля', filetypes=[('Профиль OpenCode', '*.profile.json'), ('JSON', '*.json'), ('Все файлы', '*.*')])
        if not _Lg:
            return
        try:
            _Lf = json.loads(Path(_Lg).read_text(encoding='utf-8-sig'))
        except Exception as _Le:
            messagebox.showerror('Импорт', 'Не удалось прочитать файл: %s' % _Le, parent=self.root)
            return
        if not isinstance(_Lf, dict):
            messagebox.showerror('Импорт', 'Файл не содержит объект JSON', parent=self.root)
            return
        _Ld = str(_Lf.get('id') or '').strip()
        if not re.match('^[A-Za-z0-9._-]+$', _Ld or ''):
            messagebox.showerror('Импорт', 'В файле отсутствует корректный ID профиля', parent=self.root)
            return
        _Lc = self._find(_Ld)
        if _Lc is not None and (not messagebox.askyesno('Импорт', 'Профиль «%s» уже есть. Заменить его?' % _Ld, parent=self.root)):
            return
        _Lb = {'id': _Ld, 'display_name': _Lf.get('display_name') or _Ld, 'base_url': _Lf.get('base_url') or '', 'api_key': _Lf.get('api_key') or '', 'package': _Lf.get('package') or PACKAGES[0], 'models': list(_Lf.get('models') or []), 'known_models': list(_Lf.get('known_models') or _Lf.get('models') or []), 'extra_settings': _Lf.get('extra_settings') or {}, '_raw': _Lf.get('raw') or None}
        if _Lc is not None:
            self.profiles[self.profiles.index(_Lc)] = _Lb
        else:
            self.profiles.append(_Lb)
        self.selected = _Ld
        self._render_list()
        self._set_status('ИМПОРТИРОВАН ПРОФИЛЬ %s (НЕ СОХРАНЁН)' % _Ld)

    def run(self):
        self.root.mainloop()

def _ac(_Lb: str) -> bool:
    try:
        __import__(_Lb)
        return True
    except Exception:
        return False
REQUIRED = {'certifi': ('certifi', 'актуальные корневые сертификаты для TLS')}
OPTIONAL = {'PIL': ('Pillow', 'запасной захват экрана диагностики')}

def _ad(_Lb: str) -> tuple[bool, str]:
    import subprocess
    try:
        _Le = subprocess.run([sys.executable, '-m', 'pip', 'install', '--user', '--upgrade', '--quiet', _Lb], capture_output=True, text=True, timeout=240)
        if _Le.returncode == 0:
            return (True, '')
        _Ld = (_Le.stderr or _Le.stdout or '').strip().splitlines()
        return (False, _Ld[-1] if _Ld else 'pip завершился с кодом %d' % _Le.returncode)
    except Exception as _Lc:
        return (False, str(_Lc))

def _ae() -> list:
    _Lh = []
    if not _ac('tkinter'):
        return ['tkinter не найден — переустановите Python с компонентом Tcl/Tk']
    _Lf = []
    for _Lg, (_Lb, _Lc) in REQUIRED.items():
        if not _ac(_Lg):
            _Lf.append((_Lb, _Lc))
    if getattr(sys, 'frozen', False):
        _Lf = []
    if _Lf and (not _ac('pip')):
        if getattr(sys, 'frozen', False):
            return _Lh
        try:
            import ensurepip
            ensurepip.bootstrap()
        except Exception:
            pass
    if _Lf and (not _ac('pip')):
        _Lh.append('pip недоступен — автодогрузка невозможна (python -m ensurepip)')
        return _Lh
    for _Lb, _Lc in _Lf:
        _Lh.append('Догружаю %s — %s…' % (_Lb, _Lc))
        _Ld, _Le = _ad(_Lb)
        if _Ld and _ac(_Lb):
            _Lh.append('%s установлен' % _Lb)
        else:
            _Lh.append('%s не установился: %s' % (_Lb, _Le or 'неизвестная ошибка'))
    return _Lh

def _af():
    if os.name != 'nt':
        return
    try:
        import ctypes
        _Lb = ctypes.windll.kernel32.GetConsoleWindow()
        if _Lb:
            ctypes.windll.user32.ShowWindow(_Lb, 0)
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

def main():
    _af()
    _Lc = _ae()
    _Lb = App()
    if _Lc:
        _Lb._set_status('  •  '.join(_Lc))
    _Lb.run()
    return 0
if __name__ == '__main__':
    raise SystemExit(main())