"""Small, conservative e-Naročanje importer for the local prototype.

The public detail endpoint is documented, but the complete wire schema is not.
Only an explicit, recognizable set of fields is normalized; all other successful
responses remain raw snapshots for later mapping. No API success is fabricated.
"""
import re
import math
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import requests
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from .models import SyncAttempt, Tender, TenderVersion, Notification


SOURCE_HOSTS = {"enarocanje.si", "www.enarocanje.si"}
SOURCE_LABEL = "Javne informacije Slovenije – portal javnih naročil"
ARCHIVE_ID = "1144799"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


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


def snapshot_fallback(notice_id, warning):
    if notice_id == ARCHIVE_ID:
        record = Tender.objects.filter(pk="ijs-archive").first()
        if record:
            return {"message": "Prikazan je shranjen arhivski zapis IJS, preverjen 10. 11. 2026. Svež zajem ni bil potrjen.", "tender": record, "mode": "snapshot", "warning": warning}
    record = Tender.objects.filter(pk=f"pjn-{notice_id}").first()
    if record:
        return {"message": "Prikazan je predhodno shranjen zapis. Svežega stanja vira ni bilo mogoče potrditi.", "tender": record, "mode": "snapshot", "warning": warning}
    return {"message": "Svežega uvoza ni bilo mogoče dokončati. Obstoječi podatki ostajajo na voljo.", "mode": "unavailable", "warning": warning}


def normalized_date(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def normalize_payload(payload, notice_id):
    """Accept explicit object forms only. Unknown status is never 'open'."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None

    def field(*keys):
        for key in keys:
            value = data.get(key)
            if value is not None:
                return value
        return None

    title = field("nazivNarocila", "title")
    buyer = field("narocnikNaziv", "buyer")
    source_status = field("status", "stanje")
    status_map = {"open": "open", "odprto": "open", "closed": "closed", "zaključeno": "closed", "cancelled": "cancelled", "ustavljeno": "cancelled", "preklicano": "cancelled"}
    status = status_map.get(str(source_status).strip().lower())
    if not isinstance(title, str) or not title.strip() or not isinstance(buyer, str) or not buyer.strip() or not status:
        return None
    deadline_raw = field("rokZaOddajoPonudb", "deadline")
    deadline = None
    if isinstance(deadline_raw, str):
        try:
            dt = datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = timezone.make_aware(dt)
            deadline = dt.isoformat()
        except ValueError:
            pass
    if status == "open" and deadline is None:
        return None
    kind = {"services": "services", "storitve": "services", "goods": "goods", "blago": "goods", "works": "works", "gradnje": "works"}.get(str(field("kind", "vrstaNarocila")).lower())
    if not kind:
        return None
    value = field("value", "ocenjenaVrednost")
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        value = None
    cpv = field("cpv", "cpvKode")
    cpv = [str(c)[:8] for c in cpv if re.fullmatch(r"\d{8}(?:-\d)?", str(c))] if isinstance(cpv, list) else []
    summary = field("summary", "opisNarocila")
    summary = strip_tags(summary)[:10000] if isinstance(summary, str) else "Uvoženi metapodatki. Priponke in pogoji še niso obdelani."
    return {
        "id": "ijs-archive" if notice_id == ARCHIVE_ID else f"pjn-{notice_id}", "title": strip_tags(title)[:500], "buyer": strip_tags(buyer)[:300],
        "region": str(field("region", "lokacija") or "Ni podatka")[:150], "kind": kind, "cpv": cpv,
        "value": value, "published_at": normalized_date(field("published_at", "datumObjave")),
        "deadline": deadline, "status": status, "source_type": "real",
        "source_url": f"https://www.enarocanje.si/#/pregled-objav/{notice_id}?d=1",
        "summary": summary, "description": summary, "topics": [], "technologies": [],
        "is_new": False, "has_update": False, "version": 1, "criteria": [], "lots": [], "changes": [],
        "source_metadata": {"notice_id": notice_id, "attribution": SOURCE_LABEL, "fetched_at": timezone.now().isoformat(), "attachments_processed": False},
    }


def import_notice(url_or_id):
    notice_id = parse_notice_id(url_or_id)
    day = timezone.localdate()
    with transaction.atomic():
        if SyncAttempt.objects.filter(created_at__date=day).count() >= 2:
            return snapshot_fallback(notice_id, "Dosežena je omejitev dveh zunanjih zajemov na dan. Ponoven zajem bo mogoč naslednji dan.")
        attempt = SyncAttempt.objects.create(source_id=notice_id)
    url = "https://www.enarocanje.si/api/obrazec/objava/obrazecGet"
    try:
        with requests.get(url, params={"id": notice_id}, timeout=(5, 20), allow_redirects=False, stream=True, headers={"Accept": "application/json", "User-Agent": "RazpisniRadar-Hackathon/0.1"}) as response:
            if response.status_code != 200:
                raise ValueError(f"Vir je vrnil HTTP {response.status_code}.")
            chunks = []
            total = 0
            for chunk in response.iter_content(65536):
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise ValueError("Odziv vira presega omejitev prototipa (2 MB).")
                chunks.append(chunk)
            import json
            payload = json.loads(b"".join(chunks))
        attempt.raw = payload if isinstance(payload, dict) else {"response": payload}
        attempt.success = True
        attempt.save(update_fields=["raw", "success"])
    except (requests.RequestException, ValueError, UnicodeDecodeError) as exc:
        # Do not expose proxy configuration, credentials or request headers.
        warning = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, requests.RequestException) else "Portal trenutno ni dosegljiv iz tega okolja."
        warning = warning[:250]
        attempt.error = warning
        attempt.save(update_fields=["error"])
        return snapshot_fallback(notice_id, warning)
    normalized = normalize_payload(payload, notice_id)
    if normalized is None:
        attempt.error = "Izvorni JSON je shranjen, njegova struktura pa še nima preverjene preslikave."
        attempt.save(update_fields=["error"])
        return snapshot_fallback(notice_id, attempt.error)
    with transaction.atomic():
        record = Tender.objects.filter(pk=normalized["id"]).first()
        if record:
            comparison = {k: v for k, v in normalized.items() if k not in {"version", "source_metadata", "changes", "has_update", "is_new"}}
            previous = {k: record.data.get(k) for k in comparison}
            if comparison != previous:
                normalized["version"] = record.data.get("version", 1) + 1
                labels = {"title": "Naslov", "summary": "Predmet", "description": "Opis", "deadline": "Rok za oddajo", "status": "Stanje", "value": "Ocenjena vrednost", "buyer": "Naročnik"}
                normalized["has_update"] = True
                normalized["changes"] = [{"field": labels.get(k, k), "before": str(previous.get(k) or "Ni podatka"), "after": str(v or "Ni podatka"), "impact": "Spremenjeni metapodatki; preverite izvorno objavo in dokumentacijo."} for k, v in comparison.items() if v != previous.get(k) and k != "description"]
                record.data = normalized
                record.save(update_fields=["data", "updated_at"])
                TenderVersion.objects.create(tender=record, version=normalized["version"], data=normalized)
                if record.following:
                    Notification.objects.get_or_create(event_key=f"import:{notice_id}:v{normalized['version']}", defaults={"tender": record, "type": "correction", "title": "Sprememba spremljane objave", "body": "Spremenjeni so metapodatki spremljanega razpisa. Preverite primerjavo in aktualne pogoje na portalu.", "is_demo": False})
        else:
            normalized["is_new"] = True
            record = Tender.objects.create(pk=normalized["id"], data=normalized)
            TenderVersion.objects.create(tender=record, version=1, data=normalized)
            from .matching import serialize_tender
            from .seed import get_profile
            evaluated = serialize_tender(record, get_profile())
            if evaluated["status"] == "open" and evaluated["match"]["level"] != "low":
                Notification.objects.get_or_create(event_key=f"import:{notice_id}:new", defaults={"tender": record, "type": "new", "title": "Nova vsebinsko relevantna objava", "body": "Predmet se ujema s profilom podjetja. Dokumentacijo in pogoje je treba še preveriti.", "is_demo": False})
    return {"message": "Metapodatki objave so uvoženi. Priponke in pogoji še niso analizirani.", "mode": "live", "tender": record, "warning": "Uvoz ne potrjuje izpolnjevanja pogojev in še ne zajema zunanjih priponk."}
