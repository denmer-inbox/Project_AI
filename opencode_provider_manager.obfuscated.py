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
    _Li = os.environ.get('SSL_CERT_FILE')
    if _Li:
        _Lg.append(Path(_Li))
    try:
        import certifi
        _Lg.append(Path(certifi.where()))
    except Exception:
        pass
    _Lh = Path(sys.prefix) / 'Lib' / 'site-packages'
    _Lg += [_Lh / 'pip' / '_vendor' / 'certifi' / 'cacert.pem', Path('C:\\Program Files\\Git\\mingw64\\etc\\ssl\\certs\\ca-bundle.crt'), Path('C:\\Program Files\\Git\\usr\\ssl\\certs\\ca-bundle.crt'), Path('C:\\Program Files\\Common Files\\SSL\\cert.pem')]
    _Lf = []
    for _Ld in _Lg:
        try:
            if _Ld and _Ld.is_file() and (_Ld.stat().st_size > 4096):
                if str(_Ld).lower() not in [str(_Le).lower() for _Le in _Lf]:
                    _Lf.append(_Ld)
        except OSError:
            continue
    return _Lf

def _f(_Lj, _Lk):
    try:
        with socket.create_connection((_Lk, 443), timeout=8) as _Ll:
            with _Lj.wrap_socket(_Ll, server_hostname=_Lk):
                return True
    except ssl.SSLCertVerificationError:
        return False
    except Exception:
        return True

def _g(_Lm):
    _Lm = (_Lm or '').lower()
    if _Lm in _CTX_CACHE:
        return _CTX_CACHE[_Lm]
    _Lp = ssl.create_default_context()
    _Lq = _f(_Lp, _Lm)
    if not _Lq:
        for _Ln in _e():
            try:
                _Lo = ssl.create_default_context(cafile=str(_Ln))
            except Exception:
                continue
            if _f(_Lo, _Lm):
                _Lp, _Lq = (_Lo, True)
                break
    _CTX_CACHE[_Lm] = _Lp
    return _Lp

def _h() -> Path:
    _Ls = os.environ.get('XDG_CONFIG_HOME')
    _Lr = Path(_Ls) if _Ls else Path.home() / '.config'
    return _Lr / 'opencode' / 'opencode.json'

def _i(_Lt: str) -> str:
    _Lz, _Lw, _L0, _Lx, _Ly = ([], 0, len(_Lt), False, False)
    while _Lw < _L0:
        _Lu = _Lt[_Lw]
        _Lv = _Lt[_Lw + 1] if _Lw + 1 < _L0 else ''
        if _Lx:
            _Lz.append(_Lu)
            if _Ly:
                _Ly = False
            elif _Lu == '\\':
                _Ly = True
            elif _Lu == '"':
                _Lx = False
            _Lw += 1
            continue
        if _Lu == '"':
            _Lx = True
            _Lz.append(_Lu)
            _Lw += 1
            continue
        if _Lu == '/' and _Lv == '/':
            while _Lw < _L0 and _Lt[_Lw] not in '\r\n':
                _Lw += 1
            continue
        if _Lu == '/' and _Lv == '*':
            _Lw += 2
            while _Lw < _L0 - 1 and (not (_Lt[_Lw] == '*' and _Lt[_Lw + 1] == '/')):
                _Lw += 1
            _Lw += 2
            continue
        _Lz.append(_Lu)
        _Lw += 1
    return re.sub(',(\\s*[}\\]])', '\\1', ''.join(_Lz))

def _j(_L1: Path) -> dict:
    if not _L1.exists():
        return {}
    _L3 = _L1.read_text(encoding='utf-8-sig')
    try:
        _L2 = json.loads(_L3)
    except json.JSONDecodeError:
        _L2 = json.loads(_i(_L3))
    if not isinstance(_L2, dict):
        raise ValueError('Корень конфига должен быть объектом JSON')
    return _L2
HISTORY_LIMIT = 50

def _k(_L4: Path) -> Path:
    return _L4.parent / 'backups'

def _l(_L5: Path) -> list:
    _Lab = []
    _L9 = []
    if _L5.exists():
        _L9 += [_L6 for _L6 in _L5.parent.glob(_L5.name + '.bak-*') if _L6.is_file()]
    _Laa = _k(_L5)
    if _Laa.is_dir():
        _L9 += [_L6 for _L6 in _Laa.glob(_L5.name + '.*.bak') if _L6.is_file()]
    for _L6 in _L9:
        _L7 = {'path': _L6, 'name': _L6.name, 'time': None, 'valid': False, 'providers': [], 'model': '', '_mtime': 0}
        try:
            _L7['time'] = datetime.fromtimestamp(_L6.stat().st_mtime)
            _L7['_mtime'] = _L6.stat().st_mtime
        except OSError:
            pass
        try:
            _L8 = _j(_L6)
            _L7['valid'] = True
            _L7['providers'] = list((_L8.get('providers') or {}).keys())
            _L7['model'] = _y(_L8)
        except Exception:
            pass
        _Lab.append(_L7)
    _Lab.sort(key=lambda e: e['_mtime'], reverse=True)
    return _Lab

def _m(_Lac: Path):
    if not _Lac.exists():
        return None
    _Lag = _k(_Lac)
    _Lag.mkdir(parents=True, exist_ok=True)
    _Laf = datetime.now()
    _Lae = _Laf.strftime('%Y%m%d-%H%M%S') + '-%03d' % (_Laf.microsecond // 1000)
    _Lad = _Lag / ('%s.%s.bak' % (_Lac.name, _Lae))
    shutil.copy2(_Lac, _Lad)
    return _Lad

def _n(_Lah: Path, _Lai: int=HISTORY_LIMIT) -> None:
    _Lap = []
    _Lao = _k(_Lah)
    if _Lao.is_dir():
        _Lap.append((_Lao, '*.bak'))
    _Lap.append((_Lah.parent, _Lah.name + '.bak-*'))
    for _Laj, _Lak in _Lap:
        _Lal = sorted((_Lan for _Lan in _Laj.glob(_Lak) if _Lan.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
        for _Lam in _Lal[_Lai:]:
            try:
                _Lam.unlink()
            except OSError:
                pass

def _o(_Laq: Path, _Lar: dict):
    _Laq.parent.mkdir(parents=True, exist_ok=True)
    _Lat = _m(_Laq)
    _Las = _Laq.with_name(_Laq.name + '.tmp')
    _Las.write_text(json.dumps(_Lar, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(_Las, _Laq)
    _n(_Laq)
    return _Lat

def _p(_Lau: Path, _Lav: Path):
    _Lay = _j(_Lav)
    if not isinstance(_Lay, dict):
        raise ValueError('Снимок не содержит объект JSON')
    _Lax = _m(_Lau)
    _Law = _Lau.with_name(_Lau.name + '.tmp')
    _Law.write_text(_Lav.read_text(encoding='utf-8-sig'), encoding='utf-8')
    os.replace(_Law, _Lau)
    _n(_Lau)
    return _Lax

def _q(_Laz: str) -> str:
    _Laz = (_Laz or '').strip()
    if not _Laz:
        return _Laz
    if not re.match('^[a-z][a-z0-9+.-]*://', _Laz, re.I):
        _Laz = 'https://' + _Laz
    return _Laz.rstrip('/')

def _r(_La0: str, _La1: str='', _La2: float=15.0):
    _La8 = urllib.request.Request(_La0, method='GET')
    _La8.add_header('Accept', 'application/json')
    _La8.add_header('User-Agent', 'opencode-provider-manager/2.0')
    if _La1:
        _La8.add_header('Authorization', 'Bearer ' + _La1)
    _La7 = urllib.parse.urlsplit(_La0).hostname or ''
    try:
        with urllib.request.urlopen(_La8, timeout=_La2, context=_g(_La7)) as _La3:
            _La4 = _La3.read().decode('utf-8', 'replace')
            _La5 = _La3.status
    except urllib.error.HTTPError as _La6:
        _La4 = _La6.read().decode('utf-8', 'replace')
        _La5 = _La6.code
    try:
        return (_La5, json.loads(_La4))
    except Exception:
        return (_La5, _La4)

def _s(_La9, _Lba) -> dict:
    try:
        _La9 = float(_La9)
        _Lbc = float(_Lba)
    except Exception:
        return {}
    if not _Lbc or _Lbc <= 0:
        return {}
    _Lbb = _La9 / _Lbc
    return {'tokens_by_coef': int(_Lbb), 'text': _v(int(_Lbb))}

def _t(_Lbd: str, _Lbe: str) -> dict:
    _Lbo = _q(_Lbd)
    if not _Lbo:
        raise ValueError('Не задан URL провайдера')
    _Lbn = [_Lbo]
    if re.search('/v\\d+[a-z]?$', _Lbo, re.I):
        _Lbn.append(_Lbo[:_Lbo.rfind('/')])
    _Lbm = []
    for _Lbf in _Lbn:
        for _Lbg in ('/balance', '/credits', '/usage'):
            _Lbh = _Lbf + _Lbg
            try:
                _Lbj, _Lbk = _r(_Lbh, _Lbe)
            except Exception as _Lbl:
                _Lbm.append('%s: %s' % (_Lbh, _Lbl))
                continue
            if _Lbj == 404:
                continue
            if _Lbj in (401, 403):
                raise PermissionError('Сервер отклонил ключ (HTTP %s)' % _Lbj)
            if _Lbj >= 400:
                _Lbm.append('%s: HTTP %s' % (_Lbh, _Lbj))
                continue
            if not isinstance(_Lbk, dict):
                continue
            _Lbi = _u(_Lbk)
            if _Lbi:
                _Lbi['url'] = _Lbh
                _Lbi['raw'] = _Lbk
                return _Lbi
    raise RuntimeError('Эндпоинт баланса не найден. Проверено: %d адрес(ов). Последние ошибки: %s' % (len(_Lbm), '; '.join(_Lbm[-3:]) or '—'))

def _u(data: dict) -> dict:
    out = {'tokens': None, 'usd': None, 'text': ''}

    def as_int(_Ldx):
        try:
            if isinstance(_Ldx, bool) or _Ldx is None:
                return None
            return int(float(_Ldx))
        except Exception:
            return None

    def as_float(_Ldy):
        try:
            if isinstance(_Ldy, bool) or _Ldy is None:
                return None
            return float(_Ldy)
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

def _v(_Lbp) -> str:
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

def _w(_Lbq: str, _Lbr: str) -> list:
    _Lb2 = _q(_Lbq)
    if not _Lb2:
        raise ValueError('Не задан URL провайдера')
    _Lb1 = []
    if re.search('/v\\d+[a-z]?$', _Lb2, re.I):
        _Lb1.append(_Lb2 + '/models')
    else:
        _Lb1 += [_Lb2 + '/v1/models', _Lb2 + '/models']
    _Lbw = None
    for _Lbs in _Lb1:
        try:
            _Lby, _Lbz = _r(_Lbs, _Lbr)
        except Exception as _Lb0:
            _Lbw = _Lb0
            continue
        if _Lby == 404:
            continue
        if _Lby in (401, 403):
            raise PermissionError('Сервер отклонил ключ (HTTP %s)' % _Lby)
        if _Lby >= 400:
            raise RuntimeError('HTTP %s при запросе %s' % (_Lby, _Lbs))
        _Lbt = _Lbz.get('data') or _Lbz.get('models') or [] if isinstance(_Lbz, dict) else _Lbz
        _Lbu = []
        for _Lbv in _Lbt or []:
            if isinstance(_Lbv, str):
                _Lbv = {'id': _Lbv}
            if not isinstance(_Lbv, dict):
                continue
            _Lbx = _Lbv.get('id') or _Lbv.get('name')
            if not _Lbx:
                continue
            _Lbu.append({'id': str(_Lbx), 'display': _Lbv.get('display_name') or _Lbv.get('name') or str(_Lbx), 'context': _Lbv.get('context_window') or _Lbv.get('contextWindow') or _Lbv.get('context_length') or _Lbv.get('max_context_tokens'), 'output': _Lbv.get('max_output_tokens') or _Lbv.get('max_tokens'), 'tools': _Lbv.get('supports_tools'), 'vision': _Lbv.get('supports_vision')})
        if _Lbu:
            return sorted(_Lbu, key=lambda m: m['display'].lower())
        _Lbw = RuntimeError('Сервер вернул пустой список моделей')
    if isinstance(_Lbw, Exception):
        raise _Lbw
    raise RuntimeError('Не удалось получить список моделей')

def _x(_Lb3: dict) -> list:
    _Lcf = _Lb3.get('providers')
    _Lce = []
    if not isinstance(_Lcf, dict):
        return _Lce
    for _Lb4, _Lb5 in _Lcf.items():
        _Lb5 = _Lb5 if isinstance(_Lb5, dict) else {}
        _Lb6 = _Lb5.get('settings') if isinstance(_Lb5.get('settings'), dict) else {}
        _Lb7 = _Lb5.get('models') if isinstance(_Lb5.get('models'), dict) else {}
        _Lb9, _Lca = ([], [])
        for _Lb8, _Lcb in _Lb7.items():
            _Lca.append(_Lb8)
            if isinstance(_Lcb, dict) and _Lcb.get('disabled'):
                continue
            _Lb9.append(_Lb8)
        for _Lb8 in _Lca:
            if _Lb8 not in _Lb9:
                continue
        _Lce.append({'id': _Lb4, 'display_name': _Lb5.get('name') or _Lb4, 'coefficient': str(_Lb5.get('_coefficient') or ''), 'base_url': _Lb6.get('baseURL') or '', 'api_key': _Lb6.get('apiKey') or '', 'package': _Lb5.get('package') or PACKAGES[0], 'models': _Lb9, 'known_models': _Lca, 'extra_settings': {_Lcc: _Lcd for _Lcc, _Lcd in _Lb6.items() if _Lcc not in ('baseURL', 'apiKey')}, '_raw': copy.deepcopy(_Lb5)})
    return _Lce

def _y(_Lcg: dict) -> str:
    _Lcj = _Lcg.get('model')
    if isinstance(_Lcj, str):
        return _Lcj
    if isinstance(_Lcj, dict):
        _Lch = _Lcj.get('providerID') or ''
        _Lci = _Lcj.get('model') or _Lcj.get('modelID') or ''
        if _Lch and _Lci:
            return '%s/%s' % (_Lch, _Lci)
    return ''

def _z(_Lck: str):
    _Lck = (_Lck or '').strip()
    if '/' not in _Lck:
        return ('', '')
    _Lcl, _Lcm = _Lck.split('/', 1)
    return (_Lcl.strip(), _Lcm.strip())

def _0(_Lcn: dict, _Lco=None) -> dict:
    _Lcr = copy.deepcopy(_Lco) if isinstance(_Lco, dict) else {}
    _Lcr.pop('disabled', None)
    _Lcr.setdefault('name', _Lcn.get('display') or _Lcn['id'])
    _Lcq = _Lcr.get('limit') if isinstance(_Lcr.get('limit'), dict) else {}
    if _Lcn.get('context'):
        _Lcq['context'] = int(_Lcn['context'])
    if _Lcn.get('output'):
        _Lcq['output'] = int(_Lcn['output'])
    if _Lcq:
        _Lcr['limit'] = _Lcq
    _Lcp = _Lcr.get('capabilities') if isinstance(_Lcr.get('capabilities'), dict) else {}
    if _Lcn.get('tools') is not None:
        _Lcp['tools'] = bool(_Lcn['tools'])
    _Lcp.setdefault('tools', True)
    if _Lcn.get('vision'):
        _Lcp['input'] = ['text', 'image']
    _Lcp.setdefault('input', ['text'])
    _Lcp.setdefault('output', ['text'])
    _Lcr['capabilities'] = _Lcp
    return _Lcr

def _1(_Lcs):
    if isinstance(_Lcs, dict):
        return {_Lcu: _1(_Lct) for _Lcu, _Lct in _Lcs.items() if not _Lcu.startswith('_')}
    if isinstance(_Lcs, list):
        return [_1(_Lct) for _Lct in _Lcs]
    return _Lcs

def _2(_Lcv: dict, _Lcw: str) -> str:
    _Lcz = _Lcv.get('providers') or {}
    _Lcy = _Lcz.get(_Lcw) or {}
    _Lcx = _Lcy.get('_coefficient')
    if _Lcx in (None, ''):
        return ''
    return str(_Lcx)

def _3(_Lc0: dict) -> dict:
    _Ldb = {}
    _Lda = _q(_Lc0.get('base_url', ''))
    if _Lda:
        _Ldb['baseURL'] = _Lda
    if _Lc0.get('api_key'):
        _Ldb['apiKey'] = _Lc0['api_key']
    for _Lc8, _Lc9 in (_Lc0.get('extra_settings') or {}).items():
        _Ldb[_Lc8] = _Lc9
    _Lc7 = copy.deepcopy(_Lc0.get('_raw') or {})
    _Lc6 = str(_Lc0.get('coefficient') or '').strip()
    if _Lc6:
        _Lc7['_coefficient'] = _Lc6
    else:
        _Lc7.pop('_coefficient', None)
    _Lc7['name'] = _Lc0.get('display_name') or _Lc0.get('id')
    _Lc7['package'] = _Lc0.get('package') or PACKAGES[0]
    if _Ldb:
        _Lc7['settings'] = _Ldb
    else:
        _Lc7.pop('settings', None)
    _Lc5 = _Lc7.get('models') if isinstance(_Lc7.get('models'), dict) else {}
    _Lc4 = {}
    for _Lc1 in _Lc0.get('models') or []:
        _Lc4[_Lc1] = _0({'id': _Lc1}, _Lc5.get(_Lc1))
    for _Lc1, _Lc2 in _Lc5.items():
        if _Lc1 in _Lc4:
            continue
        _Lc3 = copy.deepcopy(_Lc2) if isinstance(_Lc2, dict) else {}
        _Lc3['disabled'] = True
        _Lc4[_Lc1] = _Lc3
    if _Lc4:
        _Lc7['models'] = _Lc4
    else:
        _Lc7.pop('models', None)
    return _Lc7

def _4(_Ldc: dict, _Ldd: list) -> dict:
    _Ldh = copy.deepcopy(_Ldc)
    if not isinstance(_Ldh.get('providers'), dict):
        _Ldh['providers'] = {}
    _Ldh['providers'] = {_Ldg['id']: _3(_Ldg) for _Ldg in _Ldd}
    _Ldf = _y(_Ldh)
    _Lde = _z(_Ldf)[0]
    if _Ldf and _Lde not in _Ldh['providers']:
        _Ldh.pop('model', None)
    return _Ldh

_EXPORT_TYPE = 'opencode-provider-profiles'
_EXPORT_VERSION = 2

def _profile_to_export(_Lp: dict) -> dict:
    return {'id': _Lp['id'], 'display_name': _Lp['display_name'], 'coefficient': str(_Lp.get('coefficient') or ''), 'base_url': _Lp['base_url'], 'package': _Lp['package'], 'api_key': _Lp['api_key'], 'models': list(_Lp['models']), 'known_models': list(_Lp['known_models']), 'extra_settings': _Lp.get('extra_settings') or {}, 'raw': _Lp.get('_raw') or {}}

def _build_export_payload(_Lq: list, _Lr: str='') -> dict:
    _Ls = {'version': _EXPORT_VERSION, 'type': _EXPORT_TYPE, 'profiles': [_profile_to_export(_Lt) for _Lt in _Lq]}
    _Lu = (_Lr or '').strip()
    if _Lu and _Lu != '(не задана)':
        _Ls['default_model'] = _Lu
    return _Ls

def _profile_from_export(_Lv: dict) -> dict:
    if not isinstance(_Lv, dict):
        raise ValueError('запись профиля не является объектом JSON')
    _Lw = str(_Lv.get('id') or '').strip()
    if not re.match('^[A-Za-z0-9._-]+$', _Lw or ''):
        raise ValueError('отсутствует корректный ID профиля')
    _Lx = [str(_Ly) for _Ly in (_Lv.get('models') or []) if str(_Ly).strip()]
    _Lz = [str(_La) for _La in (_Lv.get('known_models') or _Lx) if str(_La).strip()]
    return {'id': _Lw, 'display_name': _Lv.get('display_name') or _Lw, 'coefficient': str(_Lv.get('coefficient') or ''), 'base_url': _Lv.get('base_url') or '', 'api_key': _Lv.get('api_key') or '', 'package': _Lv.get('package') or PACKAGES[0], 'models': _Lx, 'known_models': _Lz, 'extra_settings': _Lv.get('extra_settings') or {}, '_raw': _Lv.get('raw') or None}

def _profiles_from_export(data) -> tuple:
    if isinstance(data, list):
        _Lb, _Lc = (data, '')
    elif isinstance(data, dict):
        _Lc = str(data.get('default_model') or '').strip()
        if isinstance(data.get('profiles'), list):
            _Lb = data['profiles']
        elif data.get('id'):
            _Lb = [data]
        else:
            raise ValueError('В файле нет профилей (ожидается ключ "profiles")')
    else:
        raise ValueError('Файл не содержит объект JSON')
    _Ld = []
    for _Le, _Lf in enumerate(_Lb, 1):
        try:
            _Ld.append(_profile_from_export(_Lf))
        except ValueError as _Lg:
            raise ValueError('Профиль №%d: %s' % (_Le, _Lg))
    if not _Ld:
        raise ValueError('В файле нет ни одного профиля')
    return (_Ld, _Lc)

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
                self.lbl_balance.configure(text=self._balance_value.get('text') or '—', fg=_b._T11)
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
            except Exception as _Lhk:
                self._results.put((None, _Lhk))
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
            except Exception as _Lhl:
                self._results.put(('balance', None, _Lhl))
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

_VK_INSERT = 45
_VK_A = 65
_VK_C = 67
_VK_V = 86
_VK_X = 88
_CTRL = 0x0004
_SHORTCUT_EVENTS = {'paste': '<<Paste>>', 'copy': '<<Copy>>', 'cut': '<<Cut>>', 'select_all': '<<SelectAll>>'}
_CONTROL_KEYS = {'paste': (_VK_V,), 'copy': (_VK_C, _VK_INSERT), 'cut': (_VK_X,), 'select_all': (_VK_A,)}
_LATIN_KEYS = {'paste': ('v', 'V'), 'copy': ('c', 'C'), 'cut': ('x', 'X'), 'select_all': ('a', 'A')}
_INPUT_CLASSES = ('TEntry', 'TCombobox', 'TSpinbox', 'Entry', 'Spinbox', 'Text')

def _input_widget(_M0):
    try:
        return _M0.winfo_class() in _INPUT_CLASSES
    except Exception:
        return False

def _int_attr(_M1, _M2):
    try:
        return int(getattr(_M1, _M2, 0) or 0)
    except Exception:
        return 0

def _state_of(_M3):
    return _int_attr(_M3, 'state')

def _keycode_of(_M4):
    return _int_attr(_M4, 'keycode')

def _keysym_of(_M5):
    return str(getattr(_M5, 'keysym', '') or '')

def _shortcut_action(_M6):
    if _M6 is None:
        return None
    if not _state_of(_M6) & _CTRL:
        return None
    _M7 = _keycode_of(_M6)
    for _M8, _M9 in _CONTROL_KEYS.items():
        if _M7 in _M9:
            return _M8
    return None

class _9:

    def __init__(self, _Ldz):
        self.root = _Ldz
        self.menu = tk.Menu(_Ldz, tearoff=0, bg=_b._T3, fg=_b._T12, activebackground='#0b3547', activeforeground=_b._T6, font=_b._T15, bd=0, relief='flat')
        self.menu.add_command(label='ВЫРЕЗАТЬ        Ctrl+X', command=self._cut)
        self.menu.add_command(label='КОПИРОВАТЬ      Ctrl+C', command=self._copy)
        self.menu.add_command(label='ВСТАВИТЬ        Ctrl+V', command=self._paste)
        self.menu.add_separator()
        self.menu.add_command(label='ВЫДЕЛИТЬ ВСЁ    Ctrl+A', command=self._select_all)
        self._target = None
        self.menu.bind('<FocusOut>', lambda e: self.menu.unpost())

    def _widget(self, _Ld0):
        _Ld1 = _Ld0.widget
        return _Ld1 if _input_widget(_Ld1) else None

    def bind(self, _Ld2):
        _Ld2.bind('<Button-3>', self.popup, add='+')
        return _Ld2

    def bind_tree(self, _Ld3):
        self.bind(_Ld3)
        if _input_widget(_Ld3):
            _Ld3.bind('<Control-KeyPress>', self.on_control_key, add='+')
        for _Ld4 in _Ld3.winfo_children():
            self.bind_tree(_Ld4)

    def _target_for(self, _Ma=None):
        _Mb = getattr(_Ma, 'widget', None) if _Ma is not None else None
        if _input_widget(_Mb):
            return _Mb
        try:
            _Mb = self.root.focus_get()
        except Exception:
            _Mb = None
        return _Mb if _input_widget(_Mb) else None

    def _run_shortcut(self, _Mc, _Md):
        _Me = _SHORTCUT_EVENTS[_Md]
        if _Mc is None:
            return None
        try:
            _Mc.event_generate(_Me)
        except Exception:
            return None
        return 'break'

    def on_control_key(self, _Mf):
        _Mg = _shortcut_action(_Mf)
        if _Mg is None:
            return None
        if _keysym_of(_Mf) in _LATIN_KEYS[_Mg]:
            return None
        return self._run_shortcut(self._target_for(_Mf), _Mg)

    def _cls(self, _Ld5):
        try:
            return _Ld5.winfo_class()
        except Exception:
            return ''

    def _copy(self):
        _Ld7 = self._target
        if not _Ld7:
            return
        try:
            if self._cls(_Ld7) == 'Text':
                _Ld6 = _Ld7.get('sel.first', 'sel.last') if _Ld7.tag_ranges('sel') else _Ld7.get('1.0', 'end-1c')
            else:
                _Ld6 = _Ld7.selection_get()
        except Exception:
            _Ld6 = ''
        if _Ld6:
            self.root.clipboard_clear()
            self.root.clipboard_append(_Ld6)

    def _cut(self):
        _Ld8 = self._target
        if not _Ld8:
            return
        self._copy()
        try:
            if self._cls(_Ld8) == 'Text':
                if _Ld8.tag_ranges('sel'):
                    _Ld8.delete('sel.first', 'sel.last')
            else:
                _Ld8.delete('sel.first', 'sel.last')
        except Exception:
            pass

    def _paste(self):
        _Lea = self._target
        if not _Lea:
            return
        _Ld9 = self._read_clip()
        if not _Ld9:
            return
        self._insert_text(_Lea, _Ld9)

    def _select_all(self):
        _Leb = self._target
        if not _Leb:
            return
        try:
            if self._cls(_Leb) == 'Text':
                _Leb.tag_add('sel', '1.0', 'end-1c')
            else:
                _Leb.selection_range(0, 'end')
                _Leb.icursor('end')
        except Exception:
            pass

    def _read_clip(self):
        try:
            return self.root.clipboard_get()
        except Exception:
            return ''

    def _insert_text(self, _Leg, _Leh):
        try:
            if str(_Leg.cget('state')) == 'readonly':
                return
        except Exception:
            pass
        try:
            try:
                _Leg.delete('sel.first', 'sel.last')
            except Exception:
                pass
            _Leg.insert('insert', _Leh)
        except Exception:
            pass

    def popup(self, _Lei):
        _Lej = self._widget(_Lei)
        if _Lej is None:
            return 'break'
        self._target = _Lej
        try:
            self.menu.tk_popup(_Lei.x_root, _Lei.y_root)
        finally:
            self.menu.grab_release()
        return 'break'

def _ab(root):
    menu = _9(root)
    for _Mh in _INPUT_CLASSES:
        try:
            root.bind_class(_Mh, '<Control-KeyPress>', menu.on_control_key, add='+')
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
        _Lfj = self.root
        _Lfi = tk.Frame(_Lfj, bg=_b._T1)
        _Lfi.pack(fill='x', padx=16, pady=(14, 4))
        _Lfh = tk.Frame(_Lfi, bg=_b._T1)
        _Lfh.pack(side='left', padx=(2, 20))
        tk.Label(_Lfh, text='OPENCODE', bg=_b._T1, fg=_b._T6, font=_b._T17).pack(anchor='w')
        tk.Label(_Lfh, text='ПРОВАЙДЕРЫ И МОДЕЛИ', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(anchor='w')
        _Lfg = tk.Frame(_Lfi, bg=_b._T1)
        _Lfg.pack(side='left', fill='x', expand=True, padx=8)
        tk.Label(_Lfg, text='КОНФИГУРАЦИЯ', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(anchor='w')
        self.var_path = tk.StringVar(value=str(self.config_path))
        ttk.Entry(_Lfg, textvariable=self.var_path, font=_b._T14).pack(fill='x', pady=(2, 0))
        _Lff = tk.Frame(_Lfi, bg=_b._T1)
        _Lff.pack(side='right', padx=(8, 2))
        ttk.Button(_Lff, text='ОТКРЫТЬ ПАПКУ', command=self._open_folder).pack(side='left', padx=3)
        ttk.Button(_Lff, text='ПЕРЕЗАГРУЗИТЬ', command=self.load).pack(side='left', padx=3)
        _d(_Lfj, color=_b._T6).pack(fill='x', padx=16, pady=(6, 0))
        _Lfe = tk.Frame(_Lfj, bg=_b._T1)
        _Lfe.pack(fill='both', expand=True, padx=16, pady=8)
        _Lfd = tk.Frame(_Lfe, bg=_b._T1, width=430, highlightthickness=1, highlightbackground=_b._T5)
        _Lfd.pack(side='left', fill='y', padx=(0, 10))
        _Lfd.pack_propagate(False)
        _Lfc = tk.Frame(_Lfd, bg=_b._T2)
        _Lfc.pack(fill='x', padx=10, pady=(10, 6))
        tk.Label(_Lfc, text='ПРОФИЛИ', bg=_b._T2, fg=_b._T6, font=_b._T16).pack(side='left')
        self.lbl_count = tk.Label(_Lfc, text='0', bg=_b._T2, fg=_b._T13, font=_b._T15)
        self.lbl_count.pack(side='right')
        _Lfb = tk.Frame(_Lfd, bg=_b._T2)
        _Lfb.pack(fill='both', expand=True, padx=8, pady=4)
        self.tree = ttk.Treeview(_Lfb, columns=('name', 'url'), show='headings', selectmode='browse')
        self.tree.heading('name', text='ПРОФИЛЬ')
        self.tree.heading('url', text='URL')
        self.tree.column('name', width=150, anchor='w')
        self.tree.column('url', width=245, anchor='w')
        _Lfa = ttk.Scrollbar(_Lfb, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=_Lfa.set)
        self.tree.pack(side='left', fill='both', expand=True)
        _Lfa.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._on_select())
        self.tree.bind('<Double-1>', lambda e: self.edit_profile())
        _Le9 = tk.Frame(_Lfd, bg=_b._T2)
        _Le9.pack(fill='x', padx=8, pady=(6, 10))
        ttk.Button(_Le9, text='+ ДОБАВИТЬ', style='Accent.TButton', command=self.add_profile).pack(side='left', padx=(2, 3), pady=4)
        ttk.Button(_Le9, text='ИЗМЕНИТЬ', command=self.edit_profile).pack(side='left', padx=3)
        ttk.Button(_Le9, text='УДАЛИТЬ', style='Danger.TButton', command=self.delete_profile).pack(side='left', padx=3)
        _Le8 = tk.Frame(_Lfe, bg=_b._T1, highlightthickness=1, highlightbackground=_b._T5)
        _Le8.pack(side='left', fill='both', expand=True)
        _Le7 = tk.Frame(_Le8, bg=_b._T2)
        _Le7.pack(fill='x', padx=12, pady=(10, 2))
        tk.Label(_Le7, text='ПРОФИЛЬ', bg=_b._T2, fg=_b._T13, font=_b._T15).pack(anchor='w')
        self.lbl_title = tk.Label(_Le7, text='— НЕ ВЫБРАН —', bg=_b._T2, fg=_b._T6, font=_b._T17)
        self.lbl_title.pack(anchor='w', pady=(2, 0))
        _Le6 = tk.Frame(_Le8, bg=_b._T2)
        _Le6.pack(fill='x', padx=10, pady=(8, 4))
        self.detail_vars = {}
        for _Le2, (_Le4, _Le5) in enumerate([('ID', 'id'), ('НАЗВАНИЕ', 'display_name'), ('URL', 'base_url'), ('API KEY', 'api_key'), ('ТРАНСПОРТ', 'package')]):
            tk.Label(_Le6, text=_Le4, bg=_b._T2, fg=_b._T13, font=_b._T15, width=11, anchor='w').grid(row=_Le2, column=0, sticky='w', padx=(6, 8), pady=3)
            _Le3 = tk.StringVar()
            self.detail_vars[_Le5] = _Le3
            _Lew = ttk.Entry(_Le6, textvariable=_Le3, font=_b._T14)
            _Lew.grid(row=_Le2, column=1, sticky='ew', padx=6, pady=3)
            _Lew.configure(state='readonly')
            if _Le5 == 'api_key':
                _Lew.configure(show='•')
                ttk.Button(_Le6, text='ПОКАЗАТЬ', command=lambda e=_Lew: self._toggle_entry(e)).grid(row=_Le2, column=2, padx=6)
        _Le6.columnconfigure(1, weight=1)
        _Le1 = tk.Frame(_Le8, bg=_b._T2)
        _Le1.pack(fill='x', padx=12, pady=(10, 0))
        tk.Label(_Le1, text='БАЛАНС', bg=_b._T2, fg=_b._T13, font=_b._T15).pack(side='left')
        self.lbl_balance_main = tk.Label(_Le1, text='—', bg=_b._T2, fg=_b._T13, font=_b._T14)
        self.lbl_balance_main.pack(side='left', padx=(10, 8))
        self.btn_balance_main = ttk.Button(_Le1, text='ОБНОВИТЬ', command=self.request_balance)
        self.btn_balance_main.pack(side='right', padx=2)
        self.lbl_balance_when = tk.Label(_Le1, text='', bg=_b._T2, fg=_b._T8, font=_b._T15)
        self.lbl_balance_when.pack(side='right', padx=8)
        self.lbl_balance_est_main = tk.Label(_Le8, text='', bg=_b._T2, fg=_b._T7, font=_b._T15, anchor='w')
        self.lbl_balance_est_main.pack(fill='x', padx=18, pady=(1, 0))
        _Le0 = tk.Frame(_Le8, bg=_b._T2)
        _Le0.pack(fill='x', padx=12, pady=(10, 2))
        tk.Label(_Le0, text='МОДЕЛИ ПРОФИЛЯ', bg=_b._T2, fg=_b._T13, font=_b._T15).pack(side='left')
        self.lbl_models_count = tk.Label(_Le0, text='', bg=_b._T2, fg=_b._T9, font=_b._T15)
        self.lbl_models_count.pack(side='right')
        self.lst_models = tk.Listbox(_Le8, height=4, bg=_b._T4, fg=_b._T7, selectbackground='#0b3547', selectforeground=_b._T6, relief='flat', font=_b._T15, highlightthickness=1, highlightbackground=_b._T5)
        self.lst_models.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        self.lst_models.bind('<Double-1>', lambda e: self.make_default())
        self.lst_models.bind('<Return>', lambda e: self.make_default())
        _Lez = tk.Frame(_Le8, bg=_b._T2)
        _Lez.pack(fill='x', padx=12, pady=(0, 6))
        ttk.Button(_Lez, text='ИЗМЕНИТЬ ПРОФИЛЬ…', style='Accent.TButton', command=self.edit_profile).pack(side='left', fill='x', expand=True, padx=(2, 4), pady=4)
        ttk.Button(_Lez, text='ПО УМОЛЧАНИЮ', command=self.make_default).pack(side='left', fill='x', expand=True, padx=(4, 2), pady=4)
        _d(_Lfj, color=_b._T9).pack(fill='x', padx=16, pady=(2, 0))
        _Ley = tk.Frame(_Lfj, bg=_b._T1)
        _Ley.pack(fill='x', padx=16, pady=(8, 6))
        _Lex = tk.Frame(_Ley, bg=_b._T1)
        _Lex.pack(fill='x')
        tk.Label(_Lex, text='МОДЕЛЬ ПО УМОЛЧАНИЮ', bg=_b._T1, fg=_b._T13, font=_b._T15).pack(side='left', padx=(4, 10))
        self.var_default_model = tk.StringVar()
        _Lew = ttk.Entry(_Lex, textvariable=self.var_default_model, font=_b._T14)
        _Lew.configure(state='readonly')
        _Lew.pack(side='left', fill='x', expand=True, padx=4, pady=4)
        ttk.Button(_Lex, text='ПРИМЕНИТЬ К КОНФИГУ', style='Accent.TButton', command=self.write_config).pack(side='left', padx=(8, 4))
        self.lbl_dirty = tk.Label(_Lex, text='', bg=_b._T1, fg=_b._T9, font=_b._T15)
        self.lbl_dirty.pack(side='left', padx=(6, 2))
        _Lev = tk.Frame(_Ley, bg=_b._T1)
        _Lev.pack(fill='x', pady=(6, 0))
        ttk.Button(_Lev, text='ИСТОРИЯ И ОТКАТ…', command=self.open_history).pack(side='left', padx=3)
        ttk.Button(_Lev, text='СНИМОК СЕЙЧАС', command=lambda: self.snapshot_now('Ручной снимок')).pack(side='left', padx=3)
        ttk.Button(_Lev, text='ЭКСПОРТ ВСЕХ ПРОФИЛЕЙ…', command=self.export_profile).pack(side='left', padx=3)
        ttk.Button(_Lev, text='ИМПОРТ ПРОФИЛЕЙ…', command=self.import_profile).pack(side='left', padx=3)
        self.hist_info = tk.Label(_Lev, text='Снимков: 0', bg=_b._T1, fg=_b._T7, font=_b._T15, anchor='e')
        self.hist_info.pack(side='right', padx=(6, 10))
        tk.Frame(_Lev, bg=_b._T1).pack(side='left', fill='x', expand=True)
        tk.Label(_Lfj, text='CTRL+Z — ОТКАТ К ПРЕДЫДУЩЕЙ ВЕРСИИ', bg=_b._T1, fg=_b._T8, font=_b._T15).pack(anchor='w', padx=22, pady=(0, 2))
        _Leu = tk.Frame(_Lfj, bg=_b._T3, height=26)
        _Leu.pack(fill='x', side='bottom')
        _Leu.pack_propagate(False)
        self.status = tk.Label(_Leu, text='', bg=_b._T3, fg=_b._T7, font=_b._T15, anchor='w')
        self.status.pack(side='left', fill='x', expand=True, padx=14)

    def _toggle_entry(self, _Lfk):
        _Lfl = _Lfk.cget('show') == ''
        _Lfk.configure(show='•' if _Lfl else '')

    def load(self):
        _Lfn = Path(self.var_path.get().strip() or _h())
        self.config_path = _Lfn
        try:
            self.config = _j(_Lfn)
            self.profiles = _x(self.config)
        except Exception as _Lfm:
            messagebox.showerror('Чтение конфига', 'Не удалось прочитать:\n%s\n\n%s' % (_Lfn, _Lfm))
            self.config, self.profiles = ({}, [])
        self.var_default_model.set(_y(self.config) or '(не задана)')
        self._render_list()
        self._refresh_history()
        self._base_signature = self._signature()
        self._set_status('ЗАГРУЖЕНО ПРОФИЛЕЙ: %d   •   %s' % (len(self.profiles), _Lfn))

    def _signature(self) -> str:
        try:
            return json.dumps([self.config, self.profiles], sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return ''

    def _is_dirty(self) -> bool:
        return self._base_signature != self._signature()

    def _refresh_dirty_marker(self):
        _Lfo = getattr(self, 'lbl_dirty', None)
        if _Lfo is None:
            return
        try:
            _Lfo.configure(text='● ЕСТЬ НЕСОХРАНЁННЫЕ ИЗМЕНЕНИЯ' if self._is_dirty() else '')
        except Exception:
            pass

    def _set_status(self, _Lfp):
        try:
            self.status.configure(text=_Lfp)
        except Exception:
            pass

    def _render_list(self):
        self.tree.delete(*self.tree.get_children())
        for _Lfq in self.profiles:
            self.tree.insert('', 'end', iid=_Lfq['id'], values=(_Lfq['display_name'], _Lfq['base_url']))
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

    def _find(self, _Lfr):
        for _Lfs in self.profiles:
            if _Lfs['id'] == _Lfr:
                return _Lfs
        return None

    def _on_select(self):
        _Lf0 = self.tree.selection()
        if not _Lf0:
            self._clear_details()
            return
        self.selected = _Lf0[0]
        _Lfz = self._find(self.selected)
        if not _Lfz:
            return
        self.lbl_title.configure(text=(_Lfz['display_name'] or _Lfz['id']).upper())
        for _Lfy in ('id', 'display_name', 'base_url', 'package'):
            self.detail_vars[_Lfy].set(_Lfz[_Lfy])
        _Lfy = _Lfz['api_key']
        self.detail_vars['api_key'].set('(не задан)' if not _Lfy else _Lfy[:6] + '…' + _Lfy[-4:] if len(_Lfy) > 12 else '••••')
        self.lst_models.delete(0, 'end')
        for _Lfx in _Lfz['models']:
            self.lst_models.insert('end', _Lfx)
        if _Lfz['models']:
            _Lft = self.var_default_model.get()
            _Lfu = str(_Lfz['id']) + '/'
            _Lfv = 0
            if _Lft.startswith(_Lfu):
                _Lfw = _Lft[len(_Lfu):]
                if _Lfw in _Lfz['models']:
                    _Lfv = _Lfz['models'].index(_Lfw)
            self.lst_models.selection_set(_Lfv)
            self.lst_models.see(_Lfv)
        else:
            self.lst_models.insert('end', '(модели не выбраны)')
        try:
            self.lbl_models_count.configure(text=str(len(_Lfz['models'])))
            self.lst_models.configure(height=max(3, min(10, len(_Lfz['models']) or 3)))
        except Exception:
            pass
        self._show_balance(_Lfz)
        if not _Lfz.get('_balance') and (not _Lfz.get('_balance_tried')):
            _Lfz['_balance_tried'] = True
            self.root.after(250, self.request_balance)

    def _clear_details(self):
        self.lbl_title.configure(text='— НЕ ВЫБРАН —')
        for _Lf1 in self.detail_vars.values():
            _Lf1.set('')
        self.lst_models.delete(0, 'end')

    def add_profile(self):
        _Lf3 = _5(self, None)
        self.root.wait_window(_Lf3)
        _Lf2 = _Lf3.result
        if not _Lf2:
            return
        self.profiles.append(self._from_dialog(_Lf2))
        self._render_list()
        self.tree.selection_set(_Lf2['id'])
        self._set_status('ДОБАВЛЕН ПРОФИЛЬ %s (НЕ СОХРАНЁН)' % _Lf2['id'])
        self._refresh_dirty_marker()
        if _Lf2.get('set_default') and _Lf2['models']:
            self.var_default_model.set('%s/%s' % (_Lf2['id'], _Lf2['models'][0]))

    def edit_profile(self):
        if not self.selected:
            messagebox.showinfo('Изменить', 'Выберите профиль в списке', parent=self.root)
            return
        _Lf7 = self._find(self.selected)
        if not _Lf7:
            return
        _Lf6 = _5(self, _Lf7)
        self.root.wait_window(_Lf6)
        _Lf5 = _Lf6.result
        if not _Lf5:
            return
        _Lf4 = self.profiles.index(_Lf7)
        self.profiles[_Lf4] = self._from_dialog(_Lf5)
        self.selected = _Lf5['id']
        self._render_list()
        self._set_status('ПРОФИЛЬ %s ОБНОВЛЁН (НЕ СОХРАНЁН)' % _Lf5['id'])
        self._refresh_dirty_marker()

    def _from_dialog(self, _Lf8):
        return {'id': _Lf8['id'], 'display_name': _Lf8['display_name'], 'base_url': _Lf8['base_url'], 'api_key': _Lf8['api_key'], 'package': _Lf8['package'], 'models': list(_Lf8['models']), 'known_models': list(_Lf8['known_models']), 'coefficient': _Lf8.get('coefficient') or '', 'extra_settings': _Lf8.get('extra_settings') or {}, '_raw': _Lf8.get('_raw')}

    def delete_profile(self):
        _Lf9 = self._find(self.selected) if self.selected else None
        if not _Lf9:
            messagebox.showinfo('Удалить', 'Выберите профиль в списке', parent=self.root)
            return
        if not messagebox.askyesno('Удалить профиль', 'Удалить профиль «%s»?\n\nИз конфига он исчезнет после «ПРИМЕНИТЬ К КОНФИГУ».' % _Lf9['display_name'], parent=self.root):
            return
        self.profiles.remove(_Lf9)
        self.selected = None
        self._render_list()
        self._set_status('ПРОФИЛЬ %s УДАЛЁН ИЗ СПИСКА' % _Lf9['id'])
        self._refresh_dirty_marker()

    def make_default(self):
        _Lgb = self._find(self.selected) if self.selected else None
        if not _Lgb or not _Lgb['models']:
            messagebox.showinfo('По умолчанию', 'У выбранного профиля нет моделей', parent=self.root)
            return
        _Lga = self._selected_model()
        if not _Lga:
            if len(_Lgb['models']) == 1:
                _Lga = _Lgb['models'][0]
            else:
                _Lga = self._ask_model(_Lgb)
                if not _Lga:
                    return
        self._apply_default(_Lgb, _Lga)

    def _selected_model(self):
        try:
            _Lgc = self.lst_models.curselection()
            if _Lgc:
                _Lgd = self.lst_models.get(_Lgc[0])
                if _Lgd and _Lgd != '(модели не выбраны)':
                    return _Lgd
        except Exception:
            pass
        return None

    def _apply_default(self, _Lge, _Lgf):
        self.var_default_model.set('%s/%s' % (_Lge['id'], _Lgf))
        self._set_status('МОДЕЛЬ ПО УМОЛЧАНИЮ: %s/%s (НЕ СОХРАНЕНО)' % (_Lge['id'], _Lgf))
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
            _Lhq = lb.curselection()
            if _Lhq:
                chosen['value'] = profile['models'][_Lhq[0]]
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
            except Exception as _Lhr:
                self._balance_results.put((profile['id'], None, _Lhr))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(120, self._poll_balance)

    def _poll_balance(self):
        try:
            _Lgh, _Lgi, _Lgj = self._balance_results.get_nowait()
        except queue.Empty:
            self.root.after(120, self._poll_balance)
            return
        try:
            self.btn_balance_main.configure(state='normal')
        except Exception:
            pass
        _Lgg = self._find(_Lgh)
        if _Lgg is None:
            return
        if _Lgj is not None:
            self.lbl_balance_main.configure(text='нет данных', fg=_b._T10)
            self.lbl_balance_when.configure(text=str(_Lgj)[:70])
            _Lgg['_balance'] = None
            _Lgg['_balance_error'] = str(_Lgj)
            return
        _Lgg['_balance'] = _Lgi
        _Lgg['_balance_error'] = None
        _Lgg['_balance_at'] = datetime.now()
        if _Lgh == self.selected:
            self._show_balance(_Lgg)
        if not _Lgg.get('_balance') and (not _Lgg.get('_balance_tried')):
            _Lgg['_balance_tried'] = True
            self.root.after(250, self.request_balance)

    def _show_balance(self, _Lgk):
        _Lgp = _Lgk.get('_balance')
        _Lgo = _Lgk.get('_balance_at')
        try:
            if _Lgp:
                self.lbl_balance_main.configure(text=_Lgp.get('text') or '—', fg=_b._T11)
                self.lbl_balance_when.configure(text='обновлено %s' % _Lgo.strftime('%H:%M:%S') if _Lgo else '')
                _Lgl = str(_Lgk.get('coefficient') or '').strip()
                _Lgm = _s(_Lgp.get('tokens'), _Lgl) if _Lgl else {}
                if _Lgm:
                    self.lbl_balance_est_main.configure(text='≈ %s при коэффициенте %s' % (_Lgm['text'], _Lgl))
                elif not _Lgl:
                    self.lbl_balance_est_main.configure(text='коэффициент не задан — укажите в профиле, чтобы видеть остаток в токенах')
                else:
                    self.lbl_balance_est_main.configure(text='')
            else:
                _Lgn = _Lgk.get('_balance_error')
                self.lbl_balance_main.configure(text='—' if not _Lgn else 'нет данных', fg=_b._T13 if not _Lgn else _b._T10)
                self.lbl_balance_when.configure(text=(_Lgn or '')[:70])
                self.lbl_balance_est_main.configure(text='')
        except Exception:
            pass

    def _open_folder(self):
        try:
            os.startfile(str(self.config_path.parent))
        except Exception as _Lgq:
            messagebox.showerror('Папка', str(_Lgq), parent=self.root)

    def _refresh_history(self):
        try:
            self._history = _l(self.config_path)
        except Exception:
            self._history = []
        _Lgs = getattr(self, 'hist_info', None)
        if _Lgs is not None:
            _Lgr = self._history[0]['time'].strftime('%d.%m.%Y %H:%M:%S') if self._history and self._history[0].get('time') else '—'
            _Lgs.configure(text='Снимков: %d  •  последний: %s' % (len(self._history), _Lgr))

    def open_history(self):
        _6(self)

    def snapshot_now(self, _Lgt=''):
        try:
            _Lgu = _m(self.config_path)
        except Exception as _Lgv:
            messagebox.showerror('Снимок', str(_Lgv), parent=self.root)
            return None
        if _Lgu:
            self._refresh_history()
            self._set_status((_Lgt + '  •  ' if _Lgt else '') + 'СНИМОК: ' + _Lgu.name)
        return _Lgu

    def undo_last(self):
        if self._is_dirty():
            if not messagebox.askyesno('Откат', 'Есть неприменённые изменения в форме. Откатить файл к предыдущей версии?', parent=self.root):
                return
        self._refresh_history()
        if not self._history:
            messagebox.showinfo('Откат', 'Снимков ещё нет.', parent=self.root)
            return
        self.quick_restore(self._history[0])

    def quick_restore(self, _Lgw):
        if not _Lgw.get('valid'):
            messagebox.showerror('Откат', 'Снимок повреждён:\n%s' % _Lgw['name'], parent=self.root)
            return
        _Lgz = _Lgw['time'].strftime('%d.%m.%Y %H:%M:%S') if _Lgw.get('time') else '?'
        if not messagebox.askyesno('Откатить конфиг?', 'Восстановить версию от %s?\n\nФайл: %s\nПровайдеры: %s\nМодель: %s\n\nТекущая версия тоже сохранится в историю.' % (_Lgz, _Lgw['path'].name, ', '.join(_Lgw.get('providers') or []) or '(нет)', _Lgw.get('model') or '(не задана)'), parent=self.root):
            return
        try:
            _Lgx = _p(self.config_path, _Lgw['path'])
        except Exception as _Lgy:
            messagebox.showerror('Откат', str(_Lgy), parent=self.root)
            return
        self.load()
        self._set_status('ОТКАТ ВЫПОЛНЕН. ВЕРСИЯ ДО ОТКАТА: %s' % (_Lgx.name if _Lgx else '—'))
        messagebox.showinfo('Откат', 'Конфиг восстановлен из снимка %s.\nОткат самого отката: %s' % (_Lgw['name'], _Lgx.name if _Lgx else '—'), parent=self.root)

    def write_config(self):
        _Lg5 = self._is_dirty()
        try:
            _Lg1 = _4(self.config, self.profiles)
            _Lg2 = self.var_default_model.get().strip()
            if _Lg2 and _Lg2 != '(не задана)':
                _Lg1['model'] = _Lg2
            _Lg3 = _o(self.config_path, _Lg1)
        except Exception as _Lg4:
            messagebox.showerror('Запись конфига', str(_Lg4), parent=self.root)
            return
        self.config = _Lg1
        self.profiles = _x(self.config)
        self._base_signature = self._signature()
        self._render_list()
        self._refresh_history()
        self._refresh_dirty_marker()
        _Lg0 = 'Конфиг записан. Предыдущая версия: %s' % (_Lg3.name if _Lg3 else '—')
        self._set_status(_Lg0.upper())
        messagebox.showinfo('Готово', '%s\n\nФайл: %s\n\nОткат: кнопка «ИСТОРИЯ И ОТКАТ…» или Ctrl+Z' % (_Lg0, self.config_path), parent=self.root)
        if not _Lg5:
            self._set_status('СОХРАНЕНА КОНТРОЛЬНАЯ ТОЧКА: ' + (_Lg3.name if _Lg3 else '—'))

    def export_profile(self):
        if not self.profiles:
            messagebox.showinfo('Экспорт профилей', 'Список профилей пуст — нечего сохранять', parent=self.root)
            return
        _Lha = _build_export_payload(self.profiles, self.var_default_model.get())
        _Lg9 = str(Path.home() / 'Downloads')
        _Lg8 = filedialog.asksaveasfilename(parent=self.root, title='Экспорт всех профилей моделей', defaultextension='.json', initialdir=_Lg9 if Path(_Lg9).is_dir() else str(Path.home()), initialfile='opencode-profiles.json', filetypes=[('JSON файлы', '*.json'), ('Все файлы', '*.*')])
        if not _Lg8:
            return
        _Lg7 = Path(_Lg8)
        if _Lg7.suffix.lower() != '.json':
            _Lg7 = _Lg7.with_suffix('.json')
        try:
            _Lg7.parent.mkdir(parents=True, exist_ok=True)
            _Lg7.write_text(json.dumps(_Lha, indent=2, ensure_ascii=False), encoding='utf-8')
        except PermissionError:
            messagebox.showerror('Экспорт', 'Нет доступа к папке: %s\n\nВыберите другую папку (например, Загрузки).' % _Lg7.parent, parent=self.root)
            return
        except Exception as _Lg6:
            messagebox.showerror('Экспорт', 'Не удалось сохранить файл:\n%s\n\n%s' % (_Lg7, _Lg6), parent=self.root)
            return
        if not _Lg7.exists():
            messagebox.showerror('Экспорт', 'Файл не создан: %s' % _Lg7, parent=self.root)
            return
        self._set_status('ЭКСПОРТИРОВАНО ПРОФИЛЕЙ: %d → %s' % (len(_Lha['profiles']), _Lg7))
        messagebox.showinfo('Экспорт', 'Сохранено профилей: %d\n\nФайл:\n%s\n\nРазмер: %d байт' % (len(_Lha['profiles']), _Lg7, _Lg7.stat().st_size), parent=self.root)

    def import_profile(self):
        _Lhj = str(Path.home() / 'Downloads')
        _Lhi = filedialog.askopenfilename(parent=self.root, title='Импорт профилей', initialdir=_Lhj if Path(_Lhj).is_dir() else str(Path.home()), filetypes=[('JSON файлы', '*.json'), ('Все файлы', '*.*')])
        if not _Lhi:
            return
        _Lhh = Path(_Lhi)
        if not _Lhh.exists():
            messagebox.showerror('Импорт', 'Файл не найден:\n%s' % _Lhh, parent=self.root)
            return
        try:
            _Lhf = json.loads(_Lhh.read_text(encoding='utf-8-sig'))
        except Exception as _Lhg:
            messagebox.showerror('Импорт', 'Не удалось прочитать файл:\n%s\n\n%s' % (_Lhh, _Lhg), parent=self.root)
            return
        try:
            _Lhm, _Lhn = _profiles_from_export(_Lhf)
        except ValueError as _Lho:
            messagebox.showerror('Импорт', '%s\n\nФайл: %s' % (_Lho, _Lhh), parent=self.root)
            return
        _Lhp = [_Lhq['id'] for _Lhq in _Lhm if self._find(_Lhq['id']) is not None]
        if _Lhp and (not messagebox.askyesno('Импорт', 'Уже есть профили с такими ID:\n%s\n\nЗаменить их?' % ', '.join(_Lhp), parent=self.root)):
            return
        _Lhr = _Lhs = 0
        for _Lht in _Lhm:
            _Lhu = self._find(_Lht['id'])
            if _Lhu is not None:
                self.profiles[self.profiles.index(_Lhu)] = _Lht
                _Lhs += 1
            else:
                self.profiles.append(_Lht)
                _Lhr += 1
        if _Lhn:
            self.var_default_model.set(_Lhn)
        self.selected = _Lhm[0]['id']
        self._render_list()
        self._set_status('ИМПОРТИРОВАНО ПРОФИЛЕЙ: %d (новых %d, заменено %d) — НЕ СОХРАНЁН' % (len(_Lhm), _Lhr, _Lhs))
        messagebox.showinfo('Импорт', 'Импортировано профилей: %d\nНовых: %d\nЗаменено: %d\n\nНе забудьте «ПРИМЕНИТЬ К КОНФИГУ».' % (len(_Lhm), _Lhr, _Lhs), parent=self.root)

    def run(self):
        self.root.mainloop()

def _ac(_Ldi: str) -> bool:
    try:
        __import__(_Ldi)
        return True
    except Exception:
        return False
REQUIRED = {'certifi': ('certifi', 'актуальные корневые сертификаты для TLS')}
OPTIONAL = {'PIL': ('Pillow', 'запасной захват экрана диагностики')}

def _ad(_Ldj: str) -> tuple[bool, str]:
    import subprocess
    try:
        _Ldk = subprocess.run([sys.executable, '-m', 'pip', 'install', '--user', '--upgrade', '--quiet', _Ldj], capture_output=True, text=True, timeout=240)
        if _Ldk.returncode == 0:
            return (True, '')
        _Ldl = (_Ldk.stderr or _Ldk.stdout or '').strip().splitlines()
        return (False, _Ldl[-1] if _Ldl else 'pip завершился с кодом %d' % _Ldk.returncode)
    except Exception as _Ldm:
        return (False, str(_Ldm))

def _ae() -> list:
    _Ldt = []
    if not _ac('tkinter'):
        return ['tkinter не найден — переустановите Python с компонентом Tcl/Tk']
    _Ldr = []
    for _Lds, (_Ldn, _Ldo) in REQUIRED.items():
        if not _ac(_Lds):
            _Ldr.append((_Ldn, _Ldo))
    if getattr(sys, 'frozen', False):
        _Ldr = []
    if _Ldr and (not _ac('pip')):
        if getattr(sys, 'frozen', False):
            return _Ldt
        try:
            import ensurepip
            ensurepip.bootstrap()
        except Exception:
            pass
    if _Ldr and (not _ac('pip')):
        _Ldt.append('pip недоступен — автодогрузка невозможна (python -m ensurepip)')
        return _Ldt
    for _Ldn, _Ldo in _Ldr:
        _Ldt.append('Догружаю %s — %s…' % (_Ldn, _Ldo))
        _Ldp, _Ldq = _ad(_Ldn)
        if _Ldp and _ac(_Ldn):
            _Ldt.append('%s установлен' % _Ldn)
        else:
            _Ldt.append('%s не установился: %s' % (_Ldn, _Ldq or 'неизвестная ошибка'))
    return _Ldt

def _af():
    if os.name != 'nt':
        return
    try:
        import ctypes
        _Ldu = ctypes.windll.kernel32.GetConsoleWindow()
        if _Ldu:
            ctypes.windll.user32.ShowWindow(_Ldu, 0)
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

def main():
    _af()
    _Ldw = _ae()
    _Ldv = App()
    if _Ldw:
        _Ldv._set_status('  •  '.join(_Ldw))
    _Ldv.run()
    return 0
if __name__ == '__main__':
    raise SystemExit(main())