"""Public contracts and addenda listed separately from tender documentation on PJN.

Field meanings were verified against public ``pogodbaGet`` and ``pogodbaGetGridList`` responses on
2026-11-13: grid rows carry only scalar fields (no value, dates or parties), so details are fetched
per contract. An addendum (``tip`` "Dodatek") points to its contract through ``idPogodbaPrej`` and
carries the new end date when it extends the contract."""
import hashlib
import json
import logging
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from time import monotonic, sleep

import requests

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Contract, ContractSyncState
from .pjn_normalize import codelists, text, timestamp
from .pjn_transport import fetch_json, official_url, safe_error

log = logging.getLogger(__name__)

CONTRACT_PAGE = 100
LIST_OVERLAP = timedelta(days=2)
BUYER_YEARS = 5
BUYER_MAX_ROWS = 1000
BUYER_FRESH = timedelta(days=7)
BUYER_RETRY = timedelta(minutes=10)


def supported(tender):
    return (tender.data.get('source_type') == 'real'
            and type(tender.data.get('source_metadata', {}).get('dossier_id')) is int)


def sync_contracts(tender):
    """Refresh the complete manifest; failed responses never replace the stored manifest."""
    if not supported(tender):
        return []
    dossier = tender.data['source_metadata']['dossier_id']
    forms = fetch_json(f'obrazec/objava/dosjeObrazecGetList?idDosje={dossier}')
    if not isinstance(forms, list):
        raise ValueError('Neveljaven seznam objav dosjeja.')
    files, seen, details = {}, set(), []
    for form in forms:
        contract_id = form.get('idPogodba')
        if (type(contract_id) is not int or contract_id in seen
                or form.get('idObrazecStatus') != 100):
            continue
        seen.add(contract_id)
        contract = fetch_json(f'pogodba/pogodbaGet?id={contract_id}')
        if (not isinstance(contract, dict) or contract.get('id') != contract_id
                or contract.get('idDosje') != dossier or not isinstance(contract.get('datoteka'), list)):
            raise ValueError('Pogodba se ne ujema z dosjejem ali nima seznama datotek.')
        details.append(contract)
        for item in contract['datoteka']:
            url = item.get('url')
            if not isinstance(url, str) or not official_url(url, attachment=True):
                raise ValueError('Pogodba vsebuje neveljavno povezavo do datoteke.')
            files[url] = {'url': url, 'title': item.get('ime') or 'Pogodba.pdf',
                          'contract_id': contract_id, 'notice_number': form.get('objavaIdent', '')}
    manifest = sorted(files.values(), key=lambda item: item['url'])
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    tender.refresh_from_db()
    previous = tender.data.get('source_metadata', {})
    tender.data = {**tender.data, 'source_metadata': {**tender.data.get('source_metadata', {}),
        'contracts_seen': bool(manifest or previous.get('contract_files') or previous.get('contracts_seen')),
        'contract_files': manifest, 'contracts_digest': digest, 'contracts_synced_at': timezone.now().isoformat()}}
    tender.save(update_fields=['data'])
    # The details are already fetched; keep their contractors and dates without new requests.
    for contract in details:
        try:
            store_contract(contract)
        except ValueError as exc:
            log.warning('Contract %s not stored: %s', contract.get('id'), exc)
    return manifest


# --- Contract register -------------------------------------------------------------------------

def registration_id(value):
    """Ten-digit registration number; seven-digit legacy numbers get the '000' suffix."""
    digits = re.sub(r'\D', '', value) if isinstance(value, str) else ''
    if len(digits) == 7:
        return digits + '000'
    return digits if len(digits) == 10 else ''


def day(value):
    moment = timestamp(value)
    return moment.date() if moment else None


def iso(value):
    return value.isoformat() if value else None


def amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return value


def parties(items):
    result = []
    for item in items if isinstance(items, list) else []:
        name = text(item.get('naziv'), 300) if isinstance(item, dict) else ''
        if name:
            result.append({'name': name, 'registration_number': registration_id(item.get('maticna'))})
    return result


def cpv_of(raw):
    entry = codelists()['cpv'].get(str(raw.get('idSifCpv')))
    if entry:
        return entry['code'], entry['label']
    match = re.match(r'\s*(\d{8})\s*-\s*(.*)', raw.get('sifCpv') or '')
    return (match.group(1), match.group(2).strip()) if match else ('', '')


def is_addendum(raw):
    return raw.get('tip') == 'Dodatek' or raw.get('sifObrazecOznaka') == 'DOD'


def linked_summary(item):
    return {'id': item['id'], 'is_addendum': is_addendum(item), 'notice_number': item.get('objavaIdent') or '',
            'valid_to': iso(day(item.get('trajanjeDo'))), 'value': amount(item.get('vrednost')),
            'title': text(item.get('naziv'), 300)}


def normalize_contract(raw):
    if not isinstance(raw, dict) or type(raw.get('id')) is not int:
        raise ValueError('Pogodba nima veljavnega ID-ja.')
    addendum = is_addendum(raw)
    parent = raw.get('idPogodbaPrej') if type(raw.get('idPogodbaPrej')) is int else None
    cpv, cpv_label = cpv_of(raw)
    buyers = parties(raw.get('narocnik'))
    if not buyers and text(raw.get('narocnikNaziv'), 300):
        buyers = [{'name': text(raw.get('narocnikNaziv'), 300), 'registration_number': ''}]
    files = [{'title': text(f.get('ime'), 250) or 'Pogodba.pdf', 'url': f['url']}
             for f in raw.get('datoteka') or [] if isinstance(f, dict) and isinstance(f.get('url'), str)
             and official_url(f['url'], attachment=True)]
    linked = [linked_summary(x) for x in raw.get('dodatek') or [] if isinstance(x, dict) and type(x.get('id')) is int]
    valid_to = day(raw.get('trajanjeDo'))
    contract_type = text(raw.get('sifPogodbaTip'), 200)
    return {
        'id': raw['id'], 'is_addendum': addendum, 'parent_id': parent if addendum else None,
        'dossier_id': raw.get('idDosje') if type(raw.get('idDosje')) is int else None,
        'buyer_registration': buyers[0]['registration_number'] if buyers else '',
        'cpv': cpv, 'published_at': timestamp(raw.get('objavaDejanskaDatum')), 'valid_to': valid_to,
        'data': {
            'title': text(raw.get('naziv'), 500), 'procurement_title': text(raw.get('narociloNaziv'), 500),
            'buyers': buyers, 'contractors': parties(raw.get('izvajalec')),
            'cpv_label': cpv_label, 'kind': text(raw.get('sifNarociloVrsta'), 50),
            'contract_type': contract_type, 'framework': 'okvir' in contract_type.lower(),
            'value': amount(raw.get('vrednost')), 'concluded_on': iso(day(raw.get('datumSklenitve'))),
            'valid_from': iso(day(raw.get('trajanjeOd'))), 'valid_to': iso(valid_to),
            'notice_number': raw.get('objavaIdent') or '', 'procurement_number': raw.get('dosjeObjavaIdent') or '',
            'files': files[:5],
            # A contract lists its addenda; an addendum lists the contract it changes.
            'addenda': [x for x in linked if x['is_addendum']] if not addendum else [],
            'contract': next((x for x in linked if not x['is_addendum']), None) if addendum else None,
        },
    }


def refresh_end(contract_id):
    """Latest end date across a contract and every addendum known from either side."""
    root = Contract.objects.filter(pk=contract_id, is_addendum=False).first()
    if root is None:
        return
    listed = root.data.get('addenda') or []
    stored = list(Contract.objects.filter(parent_id=contract_id, is_addendum=True).values_list('pk', 'valid_to'))
    ends = [root.valid_to] + [date.fromisoformat(a['valid_to']) for a in listed if a.get('valid_to')] + [end for _, end in stored]
    ends = [end for end in ends if end]
    count = len({a['id'] for a in listed} | {pk for pk, _ in stored})
    Contract.objects.filter(pk=contract_id).update(effective_end=max(ends) if ends else None, addenda_count=count)


def store_contract(raw):
    item = normalize_contract(raw)
    pk = item.pop('id')
    try:
        with transaction.atomic():
            record, _ = Contract.objects.update_or_create(id=pk, defaults=item)
    except IntegrityError:
        # Another collector (a parallel backfill on another machine) created it first.
        with transaction.atomic():
            record, _ = Contract.objects.update_or_create(id=pk, defaults=item)
    refresh_end(record.parent_id if record.is_addendum else record.pk)
    return record


def fetch_contract(contract_id, session=None):
    raw = fetch_json(f'pogodba/pogodbaGet?id={int(contract_id)}', session=session)
    if not isinstance(raw, dict) or raw.get('id') != contract_id:
        raise ValueError('Portal ni vrnil zahtevane pogodbe.')
    return raw


def collect_contract(contract_id):
    """Stores a contract; an addendum of an unknown contract also fetches that contract once."""
    record = store_contract(fetch_contract(contract_id))
    if record.is_addendum and record.parent_id and not Contract.objects.filter(pk=record.parent_id).exists():
        store_contract(fetch_contract(record.parent_id))
    return record


def contract_rows(filters, max_rows=None):
    offset = 0
    while True:
        grid = fetch_json('pogodba/pogodbaGetGridList', {'startRow': offset, 'endRow': offset + CONTRACT_PAGE, **filters,
                                                          'sortModel': [{'colId': 'objavaDejanskaDatum', 'sort': 'asc'}]})
        rows = grid.get('data') if isinstance(grid, dict) else None
        total = grid.get('lastRow') if isinstance(grid, dict) else None
        if not isinstance(rows, list) or not isinstance(total, int):
            raise ValueError('Seznam pogodb nima pričakovane oblike.')
        for row in rows:
            if isinstance(row, dict) and type(row.get('id')) is int:
                yield row
        offset += len(rows)
        if not rows or offset >= total or (max_rows and offset >= max_rows):
            break


class ContractFetcher:
    """Fetches contract details on ``workers`` threads, at most ``rate`` requests per second in total.

    Threads only talk to the portal, each over its own kept-alive HTTPS session; the caller stores the
    results on its own thread, so database writes stay sequential."""

    def __init__(self, workers=1, rate=2.0):
        if not 1 <= workers <= 16 or not 0 < rate <= 50:
            raise ValueError('Vzporednih prenosov mora biti od 1 do 16, hitrost od 0 do 50 zahtevkov na sekundo.')
        self.workers, self.interval = workers, 1 / rate
        self.lock, self.next_at, self.local = threading.Lock(), 0.0, threading.local()
        self.pool = ThreadPoolExecutor(workers) if workers > 1 else None
        self.sessions = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.pool:
            self.pool.shutdown()
        for session in self.sessions:
            session.close()

    def pace(self):
        with self.lock:
            now = monotonic()
            start = max(now, self.next_at)
            self.next_at = start + self.interval
        if start > now:
            sleep(start - now)

    def one(self, contract_id):
        session = getattr(self.local, 'session', None)
        if session is None:
            session = self.local.session = requests.Session()
            with self.lock:
                self.sessions.append(session)
        self.pace()
        try:
            return contract_id, fetch_contract(contract_id, session)
        except Exception as exc:  # noqa: BLE001 - reported per contract by the caller
            return contract_id, exc

    def fetch(self, ids):
        """``(id, raw response or exception)`` in the order of ``ids``."""
        return list(self.pool.map(self.one, ids)) if self.pool else [self.one(i) for i in ids]


def store_batch(fetcher, ids, result):
    """Stores fetched contracts, then fetches unknown contracts of the addenda in a second pass."""
    parents, failed = set(), False
    for contract_id, raw in fetcher.fetch(ids):
        try:
            if isinstance(raw, Exception):
                raise raw
            record = store_contract(raw)
            if record.is_addendum and record.parent_id:
                parents.add(record.parent_id)
        except Exception as exc:  # noqa: BLE001 - one unavailable contract must not stop the window
            failed = True
            result['errors'].append({'contract_id': contract_id, 'message': safe_error(exc)})
    missing = sorted(parents - set(Contract.objects.filter(pk__in=parents).values_list('pk', flat=True)))
    for contract_id, raw in fetcher.fetch(missing):
        try:
            if isinstance(raw, Exception):
                raise raw
            store_contract(raw)
            result['parents'] += 1
        except Exception as exc:  # noqa: BLE001
            failed = True
            result['errors'].append({'contract_id': contract_id, 'message': safe_error(exc)})
    return not failed


def sync_contract_list(since=None, until=None, max_contracts=None, progress=None, workers=1, rate=2.0):
    """Imports contracts and addenda published on days since..until inclusive.

    Without ``since`` it continues from the last completed day (with a short overlap), so a daily
    call keeps the register current and a longer window backfills it. ``workers`` and ``rate`` (requests
    per second across all workers) speed up a backfill; the defaults keep the daily run gentle."""
    until = until or timezone.localdate()
    state, _ = ContractSyncState.objects.get_or_create(key='list')
    explicit = since is not None
    if since is None:
        since = state.synced_until - LIST_OVERLAP if state.synced_until else until - timedelta(days=30)
    if since > until:
        raise ValueError('Začetek obdobja je po koncu.')
    result = {'since': since.isoformat(), 'until': until.isoformat(), 'listed': 0, 'fetched': 0, 'parents': 0, 'errors': []}
    filters = {'objavaDatumOd': since.isoformat() + 'T00:00:00',
               'objavaDatumDo': (until + timedelta(days=1)).isoformat() + 'T00:00:00'}
    complete, batch = True, []
    with ContractFetcher(workers, rate) as fetcher:
        def flush():
            nonlocal complete
            if batch:
                complete = store_batch(fetcher, batch, result) and complete
                batch.clear()
                if progress:
                    progress()

        for row in contract_rows(filters):
            result['listed'] += 1
            if row['id'] in batch or Contract.objects.filter(pk=row['id']).exists():
                continue
            if max_contracts is not None and result['fetched'] >= max_contracts:
                complete = False
                break
            result['fetched'] += 1
            batch.append(row['id'])
            if len(batch) >= CONTRACT_PAGE:
                flush()
        flush()
    # The watermark means "collected without gaps up to this day", so only a complete window that
    # continues it may move it. A backfill of an older or detached period never does; otherwise the
    # daily run would resume from the end of that period and try to fill months in one run.
    state.refresh_from_db()
    continues = (state.synced_until is None and not explicit) or (
        state.synced_until is not None and since <= state.synced_until + timedelta(days=1))
    if complete and continues and (state.synced_until is None or until > state.synced_until):
        state.synced_until, state.synced_at = until, timezone.now()
        state.save(update_fields=['synced_until', 'synced_at'])
    return result


def cpv_groups(codes):
    return sorted({c[:3] for c in codes or [] if isinstance(c, str) and re.fullmatch(r'\d{8}', c)})


def buyer_key(registration, groups):
    return f"buyer:{registration}:{','.join(groups)}"


def sync_buyer_contracts(registration, cpv_codes, max_details=25, delay=0.3, force=False):
    """Contracts of one buyer in the same CPV groups (first three digits) from the last five years.

    The register is filtered by buyer on the portal; CPV is read from the grid row, so only matching
    contracts are fetched in detail. An unfinished pass is continued by the next call."""
    reg, groups = registration_id(registration), cpv_groups(cpv_codes)
    if not reg or not groups:
        return {'mode': 'skipped', 'fetched': 0, 'remaining': 0, 'errors': []}
    now = timezone.now()
    state, _ = ContractSyncState.objects.get_or_create(key=buyer_key(reg, groups))
    if not force and ((state.synced_at and now - state.synced_at < BUYER_FRESH) or
                      (state.attempted_at and now - state.attempted_at < BUYER_RETRY)):
        return {'mode': 'fresh', 'fetched': 0, 'remaining': 0, 'errors': []}
    state.attempted_at = now
    state.save(update_fields=['attempted_at'])
    cpv_by_id = {int(k): v['code'] for k, v in codelists()['cpv'].items()}
    since = timezone.localdate() - timedelta(days=365 * BUYER_YEARS)
    wanted = [row['id'] for row in contract_rows({'narocnikMaticna': reg, 'objavaDatumOd': since.isoformat() + 'T00:00:00'},
                                                 max_rows=BUYER_MAX_ROWS)
              if cpv_by_id.get(row.get('idSifCpv'), '')[:3] in groups]
    known = set(Contract.objects.filter(pk__in=wanted).values_list('pk', flat=True))
    # Newest first: when the budget runs out, the current contractor matters most.
    missing = [pk for pk in reversed(wanted) if pk not in known]
    result = {'mode': 'live', 'matched': len(wanted), 'fetched': 0, 'remaining': max(0, len(missing) - max_details), 'errors': []}
    for contract_id in missing[:max_details]:
        try:
            collect_contract(contract_id)
            result['fetched'] += 1
        except Exception as exc:  # noqa: BLE001 - keep the rest of the buyer's contracts
            result['errors'].append({'contract_id': contract_id, 'message': safe_error(exc)})
        if delay:
            sleep(delay)
    if not result['remaining'] and not result['errors']:
        state.synced_at = timezone.now()
        state.save(update_fields=['synced_at'])
    return result


def tender_buyer_registrations(tender):
    buyers = tender.data.get('source_metadata', {}).get('buyers') or []
    return list(dict.fromkeys(r for r in (registration_id(b.get('registration_number')) for b in buyers) if r))


def sync_tender_buyers(tender, max_details=25, delay=0.3, force=False):
    """Buyer contracts related to a tender's subject; at most two buyers of a joint procurement."""
    results = []
    for registration in tender_buyer_registrations(tender)[:2]:
        results.append(sync_buyer_contracts(registration, tender.data.get('cpv') or [], max_details, delay, force))
    return results
