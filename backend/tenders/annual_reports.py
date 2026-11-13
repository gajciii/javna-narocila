"""Read structured annual accounts from the public AJPES LP API."""
import math
import os

import requests
from django.core.cache import cache

from .ajpes import registration_number

SOURCE = 'https://www.ajpes.si/Letna_porocila/Ponovna_uporaba'
JOLP = 'https://www.ajpes.si/JOLP/default.asp'
HOSTS = {'https://wwwa.ajpes.si', 'https://www.ajpes.si'}


class ReportUnavailable(Exception):
    pass


def fetch(path, key, params=None):
    host = os.getenv('AJPES_LP_API_BASE', 'https://wwwa.ajpes.si').rstrip('/')
    if host not in HOSTS:
        raise ReportUnavailable
    try:
        response = requests.get(host + path, params=params, headers={'X-Api-Key': key, 'Accept': 'application/json'},
                                timeout=(3, 8), allow_redirects=False)
        if response.status_code not in (200, 404):
            raise ReportUnavailable
        payload = response.json()
        if response.status_code == 404:
            if payload.get('napaka', {}).get('koda') in ('SUBJEKT_NE_OBSTAJA', 'POROCILO_NE_OBSTAJA'):
                return None
            raise ReportUnavailable
        if payload['status'] == 'USPESNO' and isinstance(payload['podatki'], dict):
            return payload['podatki']
    except (requests.RequestException, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ReportUnavailable from exc
    raise ReportUnavailable


def number(postavke, code):
    value = postavke.get(code)
    return value if type(value) in (int, float) and math.isfinite(value) else None


def latest_report(number_input):
    result = {'source_url': SOURCE, 'jolp_url': JOLP, 'report': None}
    try:
        company = registration_number(number_input)
    except ValueError:
        return {**result, 'state': 'missing_company'}
    result['registration_number'] = company
    result['jolp_url'] = f'https://www.ajpes.si/jolp/podjetje.asp?maticna={company}'
    key = os.getenv('AJPES_LP_API_KEY', '').strip()
    if not key:
        return {**result, 'state': 'not_configured'}

    cache_key = f'ajpes-lp-v2:{company}'
    stored = cache.get(cache_key)
    if stored is not None:
        return stored
    path = f'/api/v1/subjekti/{company}'
    try:
        manifest = fetch(path, key)
        if manifest is not None and manifest.get('subjekt', {}).get('maticnaStevilka') != company:
            raise ReportUnavailable
        sources = (manifest or {}).get('viri', [])
        if not isinstance(sources, list):
            raise ReportUnavailable
        annual = [entry for entry in sources if isinstance(entry, dict) and entry.get('vrstalp') == '01'
                  and type(entry.get('leto')) is int and isinstance(entry.get('identifikatorVira'), str)
                  and entry['identifikatorVira']]
        if not annual:
            result['state'] = 'not_found'
        else:
            entry = max(annual, key=lambda row: (row['leto'], str(row.get('datumObjave') or '')))
            data = fetch(path, key, {'leto': entry['leto'], 'format': 'json', 'identifikatorVira': entry['identifikatorVira']})
            report = (data or {}).get('porocilo', {})
            if (report.get('maticnaStevilka') != company or report.get('leto') != entry['leto']
                    or report.get('identifikatorVira') != entry['identifikatorVira']
                    or not isinstance(report.get('postavke'), dict)):
                raise ReportUnavailable
            amounts = report['postavke']
            employees = number(amounts, 'T188')
            result.update(state='available', report={
                'year': report['leto'], 'period_start': report.get('datumZacetkaObdobja'),
                'period_end': report.get('datumKoncaObdobja'), 'published_at': report.get('datumObjave'),
                'net_sales': number(amounts, 'T110'), 'assets': number(amounts, 'T001'),
                'equity': number(amounts, 'T056'),
                'average_employees': employees if employees is not None and employees >= 0 else None,
            })
    except (ReportUnavailable, AttributeError, TypeError, ValueError, OverflowError):
        result['state'] = 'unavailable'
    cache.set(cache_key, result, timeout=60 if result['state'] == 'unavailable' else 3600)
    return result
