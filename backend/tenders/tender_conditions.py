"""List every participation condition of a tender from its indexed documents.

Runs once per document set (at indexing time or on demand). Each condition keeps a verbatim
quote from a retrieved passage; conditions that map to a profile field are also evaluated.
"""
import hashlib
import json
import logging
import math

from django.utils import timezone

from .ai import ai_enabled, structured_call
from .deep_relevance import fold
from .document_index import search_passages
from .documents import active_documents
from .models import TenderConditions

log = logging.getLogger(__name__)

CATEGORIES = {
    'exclusion': 'Razlogi za izključitev',
    'professional': 'Poklicna sposobnost',
    'economic': 'Ekonomska in finančna sposobnost',
    'technical': 'Tehnična in strokovna sposobnost',
    'guarantee': 'Finančna zavarovanja',
    'other': 'Drugi pogoji',
}
CHECK_KINDS = ['none', 'reference_count', 'reference_value', 'staff', 'certification', 'technology']
# Prefixes of words that open condition sections in Slovenian tender documentation.
TERMS = {'pogoj', 'sposobn', 'referenc', 'izkljuc', 'zavarovanj', 'garancij', 'bonitet', 'promet',
         'kadr', 'strokovnjak', 'certifikat', 'registr', 'dovoljenj', 'izjav', 'espd', 'dokazil',
         'odgovornost', 'insolvent', 'obvez', 'izpolnjeva', 'zahtev', 'blokad', 'davk'}
SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'conditions': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'properties': {
        'category': {'type': 'string', 'enum': list(CATEGORIES)},
        'title': {'type': 'string'}, 'requirement': {'type': 'string'},
        'passage': {'type': 'integer'}, 'quote': {'type': 'string'},
        'check': {'type': 'object', 'additionalProperties': False, 'properties': {
            'kind': {'type': 'string', 'enum': CHECK_KINDS},
            'minimum': {'type': ['number', 'null']}, 'domain': {'type': ['string', 'null']},
            'max_age_years': {'type': ['integer', 'null']},
            'technologies': {'type': 'array', 'items': {'type': 'string'}},
            'certification': {'type': ['string', 'null']}},
            'required': ['kind', 'minimum', 'domain', 'max_age_years', 'technologies', 'certification']}},
        'required': ['category', 'title', 'requirement', 'passage', 'quote', 'check']}}},
    'required': ['conditions']}
INSTRUCTION = (
    'Iz odlomkov razpisne dokumentacije naštej VSE izrecne pogoje za sodelovanje ponudnika: razloge za '
    'izključitev, poklicno sposobnost (registracija, dovoljenja), ekonomsko in finančno sposobnost (promet, '
    'bonitete, neblokiran račun), tehnično in strokovno sposobnost (reference, kadri, oprema, certifikati) '
    'in zahtevana finančna zavarovanja. Ne vključuj meril za izbiro ponudbe, rokov, navodil za oddajo ali '
    'tehničnih specifikacij predmeta. Vsak pogoj navedi enkrat. title je kratko ime pogoja (do 10 besed), '
    'requirement pa jasen povzetek zahteve s pragovi, obdobji in zahtevanimi dokazili. passage je ničelni '
    'indeks odlomka; quote je kratek DOBESEDEN citat iz tega odlomka, ki dokazuje pogoj. check izpolni le, '
    'kadar je pogoj enoznačno: reference_count (minimum = število referenc), reference_value (minimum = '
    'vrednost reference v EUR), staff (minimum = število oseb), certification (točen standard) ali '
    'technology (seznam tehnologij); domain je kratka tema reference, max_age_years obdobje v letih. '
    'Sicer je kind "none" in ostala polja null ali prazna. Piši slovensko. Če pogojev ni, vrni prazen seznam.')


def same_text(value):
    return ' '.join(value.split())


def condition_documents(tender):
    return [doc for doc in active_documents(tender, metadata_only=True)
            if doc.indexed_content_id and doc.status == 'processed' and doc.extraction.get('mode') != 'archive']


def fingerprint(documents):
    return hashlib.sha256(json.dumps(sorted((d.pk, d.indexed_content_id) for d in documents)).encode()).hexdigest()


def valid_check(check, quote):
    kind = check.get('kind')
    if kind in ('reference_count', 'reference_value', 'staff'):
        minimum = check.get('minimum')
        if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum) or minimum < 0:
            return False
    elif kind == 'certification':
        from .matching import certification_key
        name = check.get('certification')
        if not isinstance(name, str) or not name.strip() or len(name) > 150 or certification_key(name) not in certification_key(quote):
            return False
    elif kind == 'technology':
        tech = check.get('technologies')
        if not isinstance(tech, list) or not tech or not all(isinstance(t, str) and t.strip() for t in tech):
            return False
    else:
        return False
    age = check.get('max_age_years')
    return age is None or (not isinstance(age, bool) and isinstance(age, int) and 0 <= age <= 100)


def validated(answer, passages):
    result, seen = [], set()
    for item in answer.get('conditions', [])[:80]:
        position = item.get('passage')
        title, requirement = item.get('title', '').strip(), item.get('requirement', '').strip()
        quote = item.get('quote', '').strip()
        if (item.get('category') not in CATEGORIES or not 2 <= len(title) <= 300 or len(requirement) > 2000
                or len(quote) < 8 or fold(title) in seen):
            continue
        # The model sometimes cites the wrong passage index; the verbatim quote is what must hold.
        indexes = ([position] if not isinstance(position, bool) and isinstance(position, int)
                   and 0 <= position < len(passages) else []) + list(range(len(passages)))
        passage = next((passages[i] for i in indexes if same_text(quote) in same_text(passages[i]['quote'])), None)
        if passage is None:
            continue
        seen.add(fold(title))
        check = item.get('check') or {}
        result.append({'id': f'c{len(result) + 1}', 'category': item['category'], 'title': title,
                       'requirement': requirement or title, 'quote': quote,
                       'document_id': passage['document_id'], 'document_title': passage['document_title'],
                       'page': passage['page'], 'locator': passage['locator'],
                       'check': check if valid_check(check, quote) else {'kind': 'none'}})
    return result


def extract_conditions(tender, force=False):
    """Store the condition list for the tender's current documents; returns the stored record."""
    documents = condition_documents(tender)
    key = fingerprint(documents)
    record = TenderConditions.objects.filter(tender=tender).first()
    if record and record.fingerprint == key and record.mode in ('live', 'empty') and not force:
        return record
    record = record or TenderConditions(tender=tender)
    record.fingerprint = key
    if not documents:
        record.mode, record.conditions, record.message = 'empty', [], 'Razpis nima indeksirane dokumentacije.'
    else:
        passages, _ = search_passages(documents, {}, limit=40, terms=TERMS)
        if not passages:
            record.mode, record.conditions = 'empty', []
            record.message = 'V dokumentaciji ni najdenih odlomkov s pogoji za sodelovanje.'
        elif not ai_enabled():
            record.mode, record.message = 'unavailable', 'AI ni povezan; pogoji še niso izluščeni.'
        else:
            try:
                answer = structured_call(SCHEMA, INSTRUCTION, {'title': tender.data.get('title', ''), 'passages': [
                    {'document': p['document_title'], 'locator': p['locator'], 'text': p['quote']} for p in passages]},
                    # Long condition sections (20+ conditions) take the model close to a minute.
                    timeout=150)
                record.conditions = validated(answer, passages)
                record.mode = 'live' if record.conditions else 'empty'
                record.message = '' if record.conditions else 'V dokumentaciji ni najdenih pogojev s potrjenim citatom.'
            except Exception as exc:
                log.warning('Condition extraction unavailable: %s', type(exc).__name__)
                record.mode, record.message = 'unavailable', 'AI trenutno ni dosegljiv; pogoji bodo izluščeni ob naslednjem poskusu.'
    record.extracted_at = timezone.now()
    record.save()
    return record


def conditions_payload(tender, profile):
    from .matching import evaluate_requirement
    record = TenderConditions.objects.filter(tender=tender).first()
    if record is None:
        return {'mode': 'pending', 'message': 'Pogoji bodo izluščeni ob indeksiranju dokumentacije.', 'items': []}
    current = record.fingerprint == fingerprint(condition_documents(tender))
    items = []
    for item in record.conditions:
        check = item.get('check', {})
        status, company_value = 'manual', ''
        if check.get('kind', 'none') != 'none':
            evaluated = evaluate_requirement({**check, 'id': item['id'], 'title': item['title'],
                                              'requires_manual_review': False, 'quote': item['quote']}, profile)
            status, company_value = evaluated['status'], evaluated['company_value']
        items.append({**item, 'category_label': CATEGORIES[item['category']], 'status': status,
                      'company_value': company_value})
    return {'mode': record.mode, 'message': record.message, 'items': items, 'current': current,
            'extracted_at': record.extracted_at}
