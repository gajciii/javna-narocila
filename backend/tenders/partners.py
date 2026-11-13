"""Company-scoped partner facts and conservative, evidence-backed comparisons."""
from copy import deepcopy
from datetime import date
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db import transaction
from rest_framework.exceptions import ValidationError
from .models import Partner, DemoEvent, Tender
from .seed import today, get_profile
from .improvements import company_key
from .matching import evaluate_requirement, serialize_tender, text_normalize, certification_key, content_match
from .documents import active_documents
from .validation import validate_profile
from .runtime_data import application_tenders, test_fixtures_enabled

POTENTIAL_LABEL = 'Potencialno pokrito – preverite pogoje skupne prijave'


def safe_url(value):
    if not value:
        return ''
    try:
        URLValidator(schemes=['http', 'https'])(value)
    except DjangoValidationError:
        raise ValidationError('Povezava mora biti veljaven HTTP(S) URL.')
    return value


def evidence_values(value):
    if not isinstance(value, dict):
        raise ValidationError('Neveljavno dokazilo.')
    result = {}
    for key in ('source', 'url'):
        item = value.get(key, '')
        if not isinstance(item, str) or len(item) > 2000:
            raise ValidationError('Neveljaven opis ali povezava dokazila.')
        result[key] = item.strip()
    safe_url(result['url'])
    confirmed = value.get('confirmed', False)
    if not isinstance(confirmed, bool):
        raise ValidationError('Potrditev dokazila mora biti logična vrednost.')
    if confirmed and not (result['source'] or result['url']):
        raise ValidationError('Za potrditev navedite vir ali povezavo do dokazila.')
    result['confirmed'] = confirmed
    return result


def partner_values(payload, current=None):
    if not isinstance(payload, dict):
        raise ValidationError('Pričakovan je objekt partnerja.')
    source = payload.get('source_type', current.source_type if current else 'real')
    if source != 'real' and not test_fixtures_enabled():
        raise ValidationError('Dodajte dejansko podjetje in njegove sposobnosti.')
    if source not in ('real', 'demo') or (current and source != current.source_type):
        raise ValidationError('Vir partnerja mora biti real ali demo in ga ni mogoče zamenjati.')
    raw = payload.get('profile', {})
    if not isinstance(raw, dict):
        raise ValidationError('Pričakovan je profil partnerja.')
    defaults = {key: '' for key in ('name', 'registration_number', 'activity', 'address', 'website', 'description', 'capacity', 'available_from')}
    defaults.update({key: [] for key in ('expertise', 'technologies', 'keywords', 'excluded_keywords', 'regions', 'certifications', 'references')})
    defaults.update(staff_count=None, min_value=None, max_value=None)
    profile = validate_profile(raw, {**defaults, **(current.data if current else {})})
    profile.pop('id', None)
    safe_url(profile.get('website', ''))
    # Registry provenance applies to basic facts only; capability evidence is separate.
    evidence = payload.get('capability_evidence', current.data.get('capability_evidence', {}) if current else {})
    profile['capability_evidence'] = evidence_values(evidence)
    for ref in profile.get('references', []):
        if ref['confirmed'] and not (ref.get('evidence_source') or ref.get('evidence_url')):
            raise ValidationError('Pri potrjeni referenci partnerja navedite vir ali povezavo do dokazila.')
    if company_key(profile) == company_key():
        raise ValidationError('Lastnega podjetja ne dodajajte kot partnerja.')
    existing = Partner.objects.filter(company_key=company_key(), source_type=source)
    if current:
        existing = existing.exclude(pk=current.pk)
    if any(company_key(partner.data) == company_key(profile) for partner in existing):
        raise ValidationError('To podjetje je že med vašimi partnerji. Uredite obstoječi vnos.')
    return {'source_type': source, 'data': profile}


def serialize_partner(partner):
    profile = deepcopy(partner.data)
    evidence = profile.pop('capability_evidence', {})
    return {'id': partner.pk, 'source_type': partner.source_type, 'profile': profile,
            'capability_evidence': evidence, 'updated_at': partner.updated_at.isoformat()}


def proof_present(evidence):
    return evidence.get('confirmed') is True and bool(evidence.get('source') or evidence.get('url'))


def reference_evidence(ref):
    return {'source': ref.get('evidence_source', ''), 'url': ref.get('evidence_url', ''),
            'confirmed': ref.get('confirmed') is True, 'reference_id': ref.get('id'), 'title': ref.get('title', '')}


def supported_profile(partner):
    profile = deepcopy(partner.data)
    profile['references'] = [r for r in profile.get('references', []) if proof_present(reference_evidence(r))]
    if not proof_present(profile.get('capability_evidence', {})):
        profile.update(technologies=[], certifications=[], staff_count=None)
    return profile


def identified_references(company, partner):
    """Unknown identities are not pooled. Conflicting identities remain unconfirmed."""
    projects = {}
    for ref in company.get('references', []) + partner.get('references', []):
        key = text_normalize(ref.get('project_identifier', '')).strip()
        if not key or ref.get('confirmed') is not True:
            continue
        if key not in projects:
            projects[key] = deepcopy(ref)
        elif any(projects[key].get(field) != ref.get(field) for field in ('domain', 'value', 'year')):
            projects[key]['confirmed'] = False
    return list(projects.values())


def available(profile, tender):
    try:
        return date.fromisoformat(profile['available_from']) <= date.fromisoformat(tender['deadline'][:10])
    except (KeyError, ValueError, TypeError):
        return False


def relevant_evidence(requirement, profile):
    if requirement['kind'] not in ('reference_count', 'reference_value'):
        if requirement['kind'] == 'certification' and certification_key(requirement.get('certification', '')) not in {certification_key(c) for c in profile.get('certifications', [])}:
            return []
        if requirement['kind'] == 'staff' and profile.get('staff_count') is None:
            return []
        if requirement['kind'] == 'technology' and not ({text_normalize(t) for t in requirement.get('technologies', [])} & {text_normalize(t) for t in profile.get('technologies', [])}):
            return []
        return [profile.get('capability_evidence', {})] if proof_present(profile.get('capability_evidence', {})) else []
    evidence = []
    for ref in profile.get('references', []):
        single = {**requirement, 'minimum': 1} if requirement['kind'] == 'reference_count' else requirement
        if evaluate_requirement(single, {'references': [ref]})['status'] == 'met':
            evidence.append(reference_evidence(ref))
    return evidence


def compare_partner(tender, company, partner, docs, before):
    supported = supported_profile(partner)
    rows = []
    requirements = [r for d in docs if d.status == 'processed' and d.extraction.get('mode') != 'unprocessed' for r in d.extraction.get('requirements', [])]
    for req in requirements:
        own = evaluate_requirement(req, company)
        other = evaluate_requirement(req, supported)
        pooled = deepcopy(company)
        kind = req['kind']
        note = 'Način uporabe partnerjevih sposobnosti preverite v izvorni dokumentaciji.'
        if kind == 'reference_count':
            pooled['references'] = identified_references(company, supported)
            note = 'Združujemo samo potrjene reference z različnimi identifikatorji projektov. Neprepoznavnih projektov ne prištevamo.'
        elif kind == 'reference_value':
            pooled['references'] = company.get('references', []) + supported.get('references', [])
            note = 'Vrednosti različnih projektov se ne seštevajo; preverjamo posamezno referenco.'
        elif kind == 'technology':
            pooled['technologies'] = list(dict.fromkeys(company.get('technologies', []) + supported.get('technologies', [])))
        elif kind == 'staff':
            counts = [p.get('staff_count') for p in (company, supported) if available(p, before) and p.get('staff_count') is not None]
            pooled['staff_count'] = sum(counts) if counts else None
            note = 'Štejemo samo navedene kadre z znanim datumom razpoložljivosti do roka. Preverite dejansko razpoložljivost in morebitno prekrivanje ekip.'
        elif kind == 'certification':
            pooled['certifications'] = company.get('certifications', []) + supported.get('certifications', [])
            note = 'Certifikat partnerja ne postane certifikat vašega podjetja. Preverite dokazilo in za katere člane skupne prijave velja zahteva.'
        joint = evaluate_requirement(req, pooled)
        evidence = relevant_evidence(req, supported)
        partner_can_cover = other['status'] == 'met' and (kind != 'staff' or available(supported, before))
        # A partner must add an evidenced capability, not merely repeat the company's facts.
        potential = own['status'] != 'met' and bool(evidence) and (joint['status'] == 'met' or partner_can_cover)
        if kind == 'staff' and not (supported.get('staff_count') and available(supported, before)):
            potential = False
        rows.append({'condition': own, 'partner_condition': other,
                     'state': 'already_met' if own['status'] == 'met' else 'potential' if potential else 'unresolved',
                     'label': 'Že izpolnjeno po profilu' if own['status'] == 'met' else POTENTIAL_LABEL if potential else 'Ostaja odprto',
                     'explanation': note, 'evidence': evidence})
    supported_count = sum(r['state'] == 'potential' for r in rows)
    level, score, _ = content_match(tender.data, supported)
    return {'partner': serialize_partner(partner), 'supported_conditions': supported_count,
            'remaining_conditions': sum(r['state'] == 'unresolved' for r in rows),
            'content_score': score, 'content_level': level, 'conditions': rows,
            'documentation_incomplete': not docs or any(d.status != 'processed' or d.extraction.get('mode') == 'unprocessed' or d.extraction.get('rejected_requirements') for d in docs),
            'disclaimer': 'Primerjava prikazuje potencial sodelovanja. Ne potrjuje upravičenosti skupne prijave in ne spreminja profila podjetja.'}


def partner_recommendations(tender, partner_id=None):
    company = get_profile()
    ensure_demo_partners(company)
    docs = active_documents(tender)
    from .relevance import resolve_matches
    before = serialize_tender(tender, company, docs, content_result=resolve_matches([tender], company, cached_only=True)[tender.pk])
    base = {'tender_id': tender.pk, 'source_type': before['source_type'],
            'missing_conditions': [c for c in before['match']['conditions'] if c['status'] != 'met'],
            'candidates': [], 'comparison': None, 'message': ''}
    partners = Partner.objects.filter(company_key=company_key(company), source_type=before['source_type'])
    selected = None
    if partner_id is not None:
        from django.shortcuts import get_object_or_404
        selected = get_object_or_404(partners, pk=partner_id)
    if before['status'] != 'open':
        return {**base, 'message': 'Partnerje predlagamo za odprte razpise s potrjenim stanjem.'}
    if not before['match']['conditions']:
        return {**base, 'message': 'Pogoji še niso analizirani. Najprej preverite dokumentacijo.'}
    if not base['missing_conditions']:
        return {**base, 'message': 'Med obdelanimi pogoji ni odprtih vprašanj za iskanje partnerja.'}
    if before['match']['level'] == 'low':
        return {**base, 'message': 'Predmet se slabo ujema z dejavnostjo vašega podjetja. Najprej preverite vsebinsko primernost.'}
    results = [compare_partner(tender, company, p, docs, before) for p in partners if company_key(p.data) != company_key(company)]
    results.sort(key=lambda r: (-r['supported_conditions'], -r['content_score'], r['partner']['id']))
    base['candidates'] = [r for r in results if r['supported_conditions'] > 0][:3]
    if selected:
        base['comparison'] = next((r for r in results if r['partner']['id'] == selected.pk), None)
    if not base['candidates']:
        base['message'] = 'Ni partnerjev s podprtimi sposobnostmi za odprte pogoje. Dodajte partnerja in njegova dokazila ali dopolnite profil podjetja.'
    return base


def certification_catalog():
    entries = {}
    def add(value, required=False):
        key = certification_key(value)
        if not key:
            return
        entry = entries.setdefault(key, {'key': key, 'label': value, 'required': False})
        entry['required'] = entry['required'] or required
    for label in ['ISO 9001', 'ISO 14001', 'ISO/IEC 27001', 'ISO 45001']:
        add(label)
    profile = get_profile()
    for label in profile.get('certifications', []):
        add(label)
    for tender in application_tenders():
        docs = active_documents(tender)
        rendered = serialize_tender(tender, profile, docs, content_result={'mode': 'rules'})
        relevant = rendered['status'] == 'open' and rendered['match']['level'] != 'low'
        for doc in docs:
            if doc.status != 'processed' or doc.extraction.get('mode') == 'unprocessed':
                continue
            for req in doc.extraction.get('requirements', []):
                if req.get('kind') == 'certification' and req.get('certification'):
                    add(req['certification'], relevant)
    return sorted(entries.values(), key=lambda e: (not e['required'], e['label']))


@transaction.atomic
def ensure_demo_partners(profile=None):
    if not test_fixtures_enabled():
        return
    profile = profile or get_profile()
    key = company_key(profile)
    marker, created = DemoEvent.objects.get_or_create(key='partners-v1-' + key)
    if not created:
        return
    year = today().year - 1
    examples = [
        ('Športni sistemi Primer', 'sport', 85000, ['React', 'Django'], [], 3),
        ('Geo podatki Primer', 'satellite', 110000, ['Django', 'Docker'], [], 4),
        ('Integracije Primer', 'energy', 130000, ['Python', 'Django', 'WebSocket', 'MQTT'], [], 8),
        ('Varni sistemi Primer', 'software', 75000, ['React', 'Django'], ['ISO/IEC 27001'], 2),
    ]
    for index, (name, domain, value, technologies, certifications, staff) in enumerate(examples, 1):
        number = f'DEMO-P{index:02}'
        if Partner.objects.filter(company_key=key, source_type='demo', data__registration_number=number).exists():
            continue
        refs = [{'id': f'partner-ref-{index}-{i}', 'project_identifier': f'DEMO-PROJECT-{index}-{i}',
                 'title': f'Demo projekt: {domain} {i}', 'domain': domain, 'value': value, 'year': year,
                 'description': 'Razvoj in izvedba primerljive spletne oziroma podatkovne rešitve.',
                 'confirmed': True, 'evidence_source': 'Izmišljena, uporabniško potrjena demo referenca.', 'evidence_url': ''} for i in range(1, 3 if index == 2 else 2)]
        Partner.objects.create(company_key=key, source_type='demo', data={
            'name': name + ' d.o.o.', 'registration_number': number, 'address': 'Izmišljen demo naslov, Slovenija',
            'website': '', 'description': 'Razvoj spletnih aplikacij, integracij in podatkovnih rešitev.',
            'activity': 'Razvoj programske opreme', 'expertise': [domain], 'keywords': [domain],
            'technologies': technologies, 'certifications': certifications, 'staff_count': staff,
            'available_from': today().isoformat(), 'references': refs,
            'capability_evidence': {'source': 'Izmišljena demo izjava o kompetencah, kadrih in certifikatih.', 'url': '', 'confirmed': True}})
