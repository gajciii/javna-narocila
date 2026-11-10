"""Public single-notice import entry point. Wire mapping lives in pjn_normalize."""
import re
from urllib.parse import urlparse, parse_qs

SOURCE_HOSTS = {"enarocanje.si", "www.enarocanje.si"}


def parse_notice_id(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError("Vnesite ID ali povezavo do objave na e-Naročanju.")
    value = str(value).strip()
    if re.fullmatch(r"[1-9]\d{0,11}", value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in SOURCE_HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Dovoljene so samo povezave HTTPS na portal e-Naročanje.")
    fragment_match = re.search(r"(?:^|/)pregled-objav/([1-9]\d{0,11})(?:[/?]|$)", parsed.fragment or parsed.path)
    if fragment_match:
        return fragment_match.group(1)
    values = parse_qs(parsed.query).get("id", [])
    if parsed.path == "/api/obrazec/objava/obrazecGet" and len(values) == 1 and re.fullmatch(r"[1-9]\d{0,11}", values[0]):
        return values[0]
    raise ValueError("V povezavi ni prepoznanega ID-ja objave. Vnesite npr. 1144799.")


def normalize_payload(payload, notice_id):
    from .pjn_normalize import normalize_notice
    try:
        return normalize_notice(payload, notice_id)
    except (ValueError, TypeError, KeyError):
        return None


def import_notice(url_or_id):
    from .pjn_sync import import_single
    return import_single(url_or_id)
