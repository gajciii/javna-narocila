"""Public AJPES PRS data via the OPSI DataStore, verified on 2026-11-10.

This is the twice-monthly open dataset, not the authenticated restPrsInfo service.
Only basic company facts are imported; competencies and references stay empty.
"""
import hashlib
import json
import re
from datetime import timedelta

import requests
from django.utils import timezone

from .models import CompanyLookupCache

API = 'https://podatki.gov.si/api/3/action/'
DATASET = 'https://podatki.gov.si/dataset/poslovni-register-slovenije'
RESOURCE_ID = 'beb70929-3d0d-41c6-9af2-25d525d906d3'
ATTRIBUTION = 'Poslovni register Slovenije, AJPES, prek OPSI'
TTL = timedelta(hours=24)


class RegistryUnavailable(Exception):
    pass


def request_json(action, params):
    try:
        with requests.get(API + action, params=params, timeout=(5, 15), stream=True,
                          allow_redirects=False, headers={'User-Agent': 'RazpIzi/0.3', 'Accept': 'application/json'}) as response:
            if response.status_code != 200:
                raise RegistryUnavailable(f'OPSI je vrnil HTTP {response.status_code}.')
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 1024 * 1024:
                    raise RegistryUnavailable('Odziv registra presega omejitev prototipa.')
                chunks.append(chunk)
            data = json.loads(b''.join(chunks))
        if not isinstance(data, dict) or data.get('success') is not True or not isinstance(data.get('result'), dict):
            raise RegistryUnavailable('Register ni vrnil pričakovanega odziva.')
        return data['result']
    except (requests.RequestException, ValueError) as exc:
        raise RegistryUnavailable('OPSI trenutno ni dosegljiv ali ni vrnil veljavnih podatkov.') from exc


def registration_number(value):
    if not isinstance(value, str):
        raise ValueError('Vnesite 7- ali 10-mestno matično številko.')
    value = re.sub(r'\s+', '', value)
    if not re.fullmatch(r'[0-9]{7}(?:[0-9]{3})?', value):
        raise ValueError('Vnesite 7- ali 10-mestno matično številko, ne davčne številke.')
    return value + '000' if len(value) == 7 else value


def clean(row, key):
    value = row.get(key, '')
    return value.strip() if isinstance(value, str) else ''


def normalize_company(row):
    if not isinstance(row, dict):
        raise RegistryUnavailable('Nepričakovana oblika zapisa podjetja.')
    number, name = clean(row, 'Matična številka'), clean(row, 'Popolno ime')
    if not re.fullmatch(r'[0-9]{10}', number) or not name:
        raise RegistryUnavailable('Zapisu podjetja manjka naziv ali veljavna matična številka.')
    house = clean(row, 'Hišna št')
    if house.isdigit():
        house = str(int(house))
    street = ' '.join(x for x in [clean(row, 'Ulica'), house + clean(row, 'Hišna št  dodatek')] if x)
    settlement, town = clean(row, 'Naselje'), clean(row, 'Pošta')
    postal = ' '.join(x for x in [clean(row, 'Poštna št'), town] if x)
    address = ', '.join(x for x in [street, settlement if settlement not in (town, clean(row, 'Ulica')) else '', postal] if x)
    return {'name': name, 'registration_number': number, 'address': address,
            'legal_form': clean(row, 'Pravnoorganizacijska oblika'),
            'registration_authority': clean(row, 'Registrski organ')}


def cached_request(key, action, params, normalize):
    old = CompanyLookupCache.objects.filter(pk=key).first()
    if old and timezone.now() - old.fetched_at < TTL:
        return old, 'cached', False
    try:
        payload = normalize(request_json(action, params))
        record, _ = CompanyLookupCache.objects.update_or_create(key=key, defaults={
            'payload': payload, 'fetched_at': timezone.now()})
        return record, 'live', False
    except RegistryUnavailable:
        if old:
            return old, 'cached', True
        raise


def dataset_metadata():
    def normalize(data):
        if data.get('name') != 'poslovni-register-slovenije' or not any(r.get('id') == RESOURCE_ID for r in data.get('resources', [])):
            raise RegistryUnavailable('Zbirka PRS ni prepoznana.')
        return {'dataset_updated_at': data.get('metadata_modified')}
    try:
        record, _, stale = cached_request('metadata', 'package_show', {'id': 'poslovni-register-slovenije'}, normalize)
        return record.payload.get('dataset_updated_at'), stale
    except RegistryUnavailable:
        return None, True


def source_info(record, dataset_updated_at):
    return {'provider': 'ajpes', 'via': 'OPSI', 'url': DATASET, 'license': 'CC BY 4.0',
            'attribution': ATTRIBUTION, 'retrieved_at': record.fetched_at.isoformat(),
            'dataset_updated_at': dataset_updated_at, 'refresh_frequency': 'dvakrat mesečno'}


def lookup(query, exact=False):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 160:
        raise ValueError('Vnesite ime podjetja (2–160 znakov) ali matično številko.')
    query = query.strip()
    numeric = re.fullmatch(r'[0-9\s]+', query)
    number = registration_number(query) if exact or numeric else None
    key = 'company:' + number if number else 'search:' + hashlib.sha256(query.casefold().encode()).hexdigest()
    params = {'resource_id': RESOURCE_ID, 'limit': 20}
    if number:
        params['filters'] = json.dumps({'Matična številka': number})
    else:
        # String q is supported by OPSI; field-scoped q currently returns HTTP 500.
        params['q'] = query

    def normalize(data):
        rows, total = data.get('records'), data.get('total')
        if not isinstance(rows, list) or len(rows) > 20 or isinstance(total, bool) or not isinstance(total, int) or total < len(rows):
            raise RegistryUnavailable('Iskalnik registra je vrnil nepričakovane podatke.')
        companies = [normalize_company(row) for row in rows]
        if number and any(c['registration_number'] != number for c in companies):
            raise RegistryUnavailable('Matična številka v odgovoru se ne ujema z zahtevo.')
        companies.sort(key=lambda c: (c['legal_form'] == 'Poslovna enota', c['name'], c['registration_number']))
        updated, metadata_stale = dataset_metadata()
        return {'results': companies, 'total': total, 'dataset_updated_at': updated, 'metadata_stale': metadata_stale}

    record, mode, stale = cached_request(key, 'datastore_search', params, normalize)
    result = {'results': record.payload['results'], 'total': record.payload['total'],
              'source': source_info(record, record.payload.get('dataset_updated_at')), 'mode': mode, 'stale': stale}
    if stale:
        result['warning'] = 'OPSI ni dosegljiv. Prikazani so starejši shranjeni podatki; preverite datum prevzema.'
    elif record.payload.get('metadata_stale', True):
        result['warning'] = 'Datum posodobitve zbirke trenutno ni mogoče sveže preveriti.'
    return result


def blank_profile(company, source):
    return {'id': 1, 'name': company['name'], 'registration_number': company['registration_number'],
            'address': company['address'], 'activity': '', 'website': '', 'description': '',
            'expertise': [], 'technologies': [], 'keywords': [], 'excluded_keywords': [], 'regions': [],
            'min_value': None, 'max_value': None, 'available_from': '', 'staff_count': None,
            'certifications': [], 'capacity': '', 'references': [], 'source': 'user',
            'registry_source': {**source, **company}}


def preview(number):
    result = lookup(number, exact=True)
    if len(result['results']) != 1:
        raise LookupError('Podjetja s to matično številko v objavljenem naboru ni. Profil lahko izpolnite ročno.')
    company = result['results'][0]
    return {'profile': blank_profile(company, result['source']), 'source': 'ajpes',
            'mode': result['mode'], 'stale': result['stale'], 'warning': result.get('warning'),
            'message': 'Naziv, matična številka in naslov izvirajo iz javnega nabora AJPES na OPSI. Dejavnost, reference, kadre in tehnologije dopolnite sami.'}


def verified_profile_source(profile, requested):
    """Never trust client-supplied provenance; reconstruct it from server cache."""
    if not isinstance(requested, dict) or requested.get('provider') != 'ajpes':
        return None
    try:
        number = registration_number(profile.get('registration_number'))
        if number != requested.get('registration_number'):
            return None
    except ValueError:
        return None
    record = CompanyLookupCache.objects.filter(pk='company:' + number).first()
    if not record or len(record.payload.get('results', [])) != 1:
        return None
    company = record.payload['results'][0]
    return {**source_info(record, record.payload.get('dataset_updated_at')), **company}


def status():
    record = CompanyLookupCache.objects.exclude(pk='metadata').order_by('-fetched_at').first()
    return {'state': 'connected' if record else 'ready', 'provider': 'ajpes', 'via': 'OPSI', 'url': DATASET,
            'last_success': record.fetched_at.isoformat() if record else None,
            'message': 'Javni osnovni podatki PRS prek OPSI; brez API ključa. Zbirka se osvežuje dvakrat mesečno.'}
