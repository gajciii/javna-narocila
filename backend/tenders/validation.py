from copy import deepcopy
from datetime import date
import math
from rest_framework.exceptions import ValidationError


def validate_employment_report(report, registration):
    if report is None:
        return None
    if not isinstance(report, dict):
        raise ValidationError({'employment_report': 'Vnesite povprečje zaposlenih in leto poročila.'})
    from .ajpes import registration_number
    try:
        registration_number(registration)
    except ValueError as exc:
        raise ValidationError({'employment_report': 'Za podatek iz letnega poročila vnesite veljavno matično številko.'}) from exc
    average, year = report.get('average'), report.get('year')
    if (type(average) not in (int, float) or not 0 <= average <= 1e12
            or type(year) is not int or not 1900 <= year <= date.today().year):
        raise ValidationError({'employment_report': 'Vnesite nenegativno povprečje in veljavno leto poročila.'})
    return {'average': average, 'year': year}


def validate_profile(payload, current):
    if not isinstance(payload, dict):
        raise ValidationError('Profil mora biti objekt.')
    result = deepcopy(current)
    strings = ['name', 'registration_number', 'activity', 'address', 'website', 'description', 'capacity']
    arrays = ['expertise', 'technologies', 'keywords', 'excluded_keywords', 'regions', 'certifications']
    for key in strings:
        if key in payload:
            if not isinstance(payload[key], str) or len(payload[key]) > 10000:
                raise ValidationError({key: 'Vnesite besedilo do 10.000 znakov.'})
            result[key] = payload[key].strip()
    if not result.get('name'):
        raise ValidationError({'name': 'Naziv podjetja je obvezen.'})
    for key in arrays:
        if key in payload:
            values = payload[key]
            if not isinstance(values, list) or len(values) > 100 or not all(isinstance(x, str) and len(x) <= 300 for x in values):
                raise ValidationError({key: 'Pričakovan je seznam besedil.'})
            result[key] = list(dict.fromkeys(v.strip() for v in values if v.strip()))
            if key == 'certifications':
                from .matching import certification_key
                unique = {}
                for value in result[key]:
                    unique.setdefault(certification_key(value), value)
                result[key] = list(unique.values())
    for key in ['min_value', 'max_value', 'staff_count']:
        if key in payload:
            value = payload[key]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 1e12):
                raise ValidationError({key: 'Vnesite nenegativno število ali prazno vrednost.'})
            if key == 'staff_count' and value is not None and int(value) != value:
                raise ValidationError({key: 'Število sodelavcev mora biti celo število.'})
            result[key] = value
    if result.get('min_value') is not None and result.get('max_value') is not None and result['min_value'] > result['max_value']:
        raise ValidationError('Najnižja vrednost projekta ne sme presegati najvišje.')
    if 'available_from' in payload:
        try:
            result['available_from'] = date.fromisoformat(payload['available_from']).isoformat() if payload['available_from'] else ''
        except (ValueError, TypeError):
            raise ValidationError({'available_from': 'Neveljaven datum.'})
    if 'references' in payload:
        refs = payload['references']
        if not isinstance(refs, list) or len(refs) > 100:
            raise ValidationError({'references': 'Pričakovan je seznam referenc.'})
        clean = []
        ids = set()
        for index, ref in enumerate(refs):
            if not isinstance(ref, dict):
                raise ValidationError({'references': 'Neveljavna referenca.'})
            item = {}
            for key in ['id', 'title', 'description', 'domain', 'project_identifier', 'evidence_source', 'evidence_url']:
                value = ref.get(key, str(index + 1) if key == 'id' else '')
                if not isinstance(value, str) or len(value) > 5000:
                    raise ValidationError({'references': 'Neveljavno besedilo reference.'})
                item[key] = value.strip() if key in ('project_identifier', 'evidence_source', 'evidence_url') else value
            if item['evidence_url']:
                from django.core.validators import URLValidator
                from django.core.exceptions import ValidationError as DjangoValidationError
                try:
                    URLValidator(schemes=['http', 'https'])(item['evidence_url'])
                except DjangoValidationError:
                    raise ValidationError({'references': 'Povezava do dokazila mora biti veljaven HTTP(S) URL.'})
            if item['id'] in ids:
                raise ValidationError({'references': 'Reference morajo imeti različne identifikatorje.'})
            ids.add(item['id'])
            for key in ['value', 'year']:
                value = ref.get(key)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 1e12):
                    raise ValidationError({'references': 'Neveljavna vrednost ali leto reference.'})
                if key == 'year' and value is not None and (value != int(value) or not 1900 <= value <= 2200):
                    raise ValidationError({'references': 'Leto reference mora biti med 1900 in 2200.'})
                item[key] = value
            if not isinstance(ref.get('confirmed', False), bool):
                raise ValidationError({'references': 'Potrditev mora biti logična vrednost.'})
            item['confirmed'] = ref.get('confirmed', False)
            clean.append(item)
        result['references'] = clean
    result['source'] = 'user'
    from .ajpes import optional_registration_number, verified_profile_source
    employment_report = payload.get('employment_report')
    if optional_registration_number(result.get('registration_number')) != optional_registration_number(current.get('registration_number')):
        result.pop('employment_report', None)
        if employment_report == current.get('employment_report'):
            employment_report = None
    if 'employment_report' in payload:
        result['employment_report'] = validate_employment_report(employment_report, result.get('registration_number'))
    provenance = verified_profile_source(result, payload.get('registry_source', current.get('registry_source')))
    result.pop('registry_source', None)
    if provenance:
        result['registry_source'] = provenance
    result['id'] = 1
    result.pop('updated_at', None)
    return result
