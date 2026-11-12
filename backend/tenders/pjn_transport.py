"""Bounded anonymous requests to the public PJN endpoints; never forward credentials."""
import json
from urllib.parse import urljoin, urlsplit

import requests

BASE = 'https://www.enarocanje.si'
HOSTS = {'www.enarocanje.si', 'enarocanje.si'}
HEADERS = {'Accept': 'application/json', 'User-Agent': 'RazpIzi/0.2'}


def official_url(url, attachment=False):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == 'https' and parsed.hostname in HOSTS and
                 parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except (ValueError, TypeError):
        return False
    return bool(valid and (not attachment or parsed.path == '/api/datoteka/get'))


def fetch(path, body=None, max_bytes=2 * 1024 * 1024):
    url = path if path.startswith('https://') else BASE + '/api/' + path.lstrip('/')
    for redirect in range(3):
        if not official_url(url):
            raise ValueError('Vir ali preusmeritev ni uradna domena e-Naročanja.')
        call = requests.get if body is None else requests.post
        kwargs = dict(timeout=(5, 25), allow_redirects=False, stream=True, headers=HEADERS)
        if body is not None:
            kwargs['json'] = body
        with call(url, **kwargs) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                if body is not None or redirect == 2:
                    raise ValueError('Nepričakovana preusmeritev vira.')
                url = urljoin(url, response.headers.get('Location', ''))
                continue
            if response.status_code != 200:
                raise ValueError(f'Portal e-Naročanje je vrnil HTTP {response.status_code}.')
            chunks, total = [], 0
            for chunk in response.iter_content(65536):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f'Prenos presega omejitev {max_bytes // 1048576} MB.')
                chunks.append(chunk)
            return b''.join(chunks), response.headers
    raise ValueError('Preveč preusmeritev vira.')


def fetch_json(path, body=None):
    raw, _ = fetch(path, body)
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('Portal ni vrnil veljavnega JSON odziva.')


def safe_error(exc):
    if isinstance(exc, requests.RequestException):
        return 'Portal trenutno ni dosegljiv iz strežnika. Preverite omrežno povezavo.'
    return str(exc)[:300]
