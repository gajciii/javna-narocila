from urllib.parse import urlsplit
from django.core.exceptions import ImproperlyConfigured


def public_origin(value):
    """One validated origin drives hosts, CSRF and hosted browser requests."""
    value = value.strip()
    if not value:
        return '', None
    try:
        parts = urlsplit(value)
        hostname, port = parts.hostname, parts.port
        if (parts.scheme not in ('http', 'https') or not hostname or parts.username is not None or
                parts.password is not None or parts.path not in ('', '/') or parts.query or parts.fragment or
                any(c.isspace() for c in hostname)):
            raise ValueError
        hostname = hostname.encode('idna').decode('ascii').lower()
        host = f'[{hostname}]' if ':' in hostname else hostname
        suffix = f':{port}' if port is not None and (parts.scheme, port) not in (('https', 443), ('http', 80)) else ''
        return f'{parts.scheme}://{host}{suffix}', host
    except (ValueError, UnicodeError):
        raise ImproperlyConfigured('PUBLIC_APP_URL mora biti HTTP(S) izvor brez poti, gesla ali parametrov.') from None
