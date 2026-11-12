"""Pre-filled ESPD (Enotni evropski dokument v zvezi z oddajo javnega naročila) drafts.

The draft is assembled from verified sources only: tender metadata (Part I), the company
profile and AJPES registry data (Part II) and processed tender conditions with the
company's matching evidence (Part IV). Exclusion grounds (Part III) are sworn
self-declarations and are never answered automatically.
"""
import re
from copy import deepcopy
from datetime import date

from rest_framework.exceptions import ValidationError

from .documents import active_documents
from .matching import certification_key, effective_status, evaluate_requirement, text_normalize

SIZES = {'micro': 'Mikro podjetje', 'small': 'Malo podjetje', 'medium': 'Srednje podjetje', 'large': 'Veliko podjetje'}

EXCLUSION_GROUPS = [
    {'code': 'A', 'title': 'Razlogi, povezani s kazenskimi obsodbami', 'items': [
        ('participation', 'Sodelovanje v hudodelski združbi'),
        ('corruption', 'Korupcija'),
        ('fraud', 'Goljufija'),
        ('terrorism', 'Kazniva dejanja terorizma ali kazniva dejanja, povezana s terorističnimi dejavnostmi'),
        ('money_laundering', 'Pranje denarja ali financiranje terorizma'),
        ('child_labour', 'Delo otrok in druge oblike trgovine z ljudmi'),
    ]},
    {'code': 'B', 'title': 'Plačilo davkov ali prispevkov za socialno varnost', 'items': [
        ('taxes', 'Plačilo davkov (neplačane zapadle obveznosti v vrednosti 50 EUR ali več)'),
        ('social_security', 'Plačilo prispevkov za socialno varnost'),
    ]},
    {'code': 'C', 'title': 'Insolventnost, navzkrižje interesov ali poklicni prekrški', 'items': [
        ('environmental_law', 'Kršitev obveznosti na področju okoljskega prava'),
        ('social_law', 'Kršitev obveznosti na področju socialnega prava'),
        ('labour_law', 'Kršitev obveznosti na področju delovnega prava'),
        ('bankruptcy', 'Stečaj, insolventnost, prisilna poravnava ali likvidacija'),
        ('ceased_activities', 'Poslovne dejavnosti so opuščene'),
        ('misconduct', 'Velike strokovne napake'),
        ('distorting_competition', 'Dogovori z drugimi gospodarskimi subjekti za izkrivljanje konkurence'),
        ('conflict_of_interest', 'Navzkrižje interesov zaradi sodelovanja v postopku'),
        ('prior_involvement', 'Neposredna ali posredna vpletenost pri pripravi postopka'),
        ('early_termination', 'Predčasna odpoved, odškodnina ali druge primerljive sankcije'),
        ('misrepresentation', 'Lažne izjave, prikrivanje informacij ali neupravičen vpliv na postopek'),
    ]},
    {'code': 'D', 'title': 'Izključno nacionalni razlogi za izključitev', 'items': [
        ('national', 'Nacionalni razlogi po ZJN-3 (npr. izločitev zaradi negativnih referenc ali prekrškov v zvezi s plačilom za delo)'),
    ]},
]
EXCLUSION_CODES = [code for group in EXCLUSION_GROUPS for code, _ in group['items']]

SECTIONS = {
    'reference_count': ('C1', 'Tehnična in strokovna sposobnost: izvedene storitve navedene vrste'),
    'reference_value': ('C1', 'Tehnična in strokovna sposobnost: izvedene storitve navedene vrste'),
    'staff': ('C8', 'Tehnična in strokovna sposobnost: strokovno osebje'),
    'technology': ('C9', 'Tehnična in strokovna sposobnost: orodja in tehnična oprema'),
    'certification': ('D', 'Sistemi za zagotavljanje kakovosti in standardi okoljskega ravnanja'),
}

EMPTY = {
    'operator': {'vat_id': '', 'contact_name': '', 'email': '', 'phone': '', 'size': '', 'representatives': []},
    'participation': {'lots': [], 'joint_bid': None, 'joint_partners': '', 'relies_on_others': None,
                      'other_entities': '', 'subcontracting': None, 'subcontractors': ''},
    'exclusion': {},
    'selection': {'global_yes': None, 'responses': {}},
    'final': {'place': '', 'date': '', 'signatory': '', 'role': ''},
}


def _text(value, field, limit=2000):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError({field: f'Vnesite besedilo do {limit} znakov.'})
    return value.strip()


def _flag(value, field):
    if value is not None and not isinstance(value, bool):
        raise ValidationError({field: 'Pričakovan je odgovor da, ne ali prazno.'})
    return value


def clean_answers(payload, tender):
    """Validate a full answers object; unknown keys are dropped."""
    if not isinstance(payload, dict):
        raise ValidationError('Odgovori morajo biti objekt.')
    result = deepcopy(EMPTY)

    operator = payload.get('operator') or {}
    if not isinstance(operator, dict):
        raise ValidationError({'operator': 'Pričakovan je objekt.'})
    for key in ('vat_id', 'contact_name', 'email', 'phone'):
        result['operator'][key] = _text(operator.get(key), f'operator.{key}', 200)
    vat = re.sub(r'\s+', '', result['operator']['vat_id']).upper()
    if vat and not re.fullmatch(r'(SI)?\d{8}|[A-Z]{2}[0-9A-Z]{2,13}', vat):
        raise ValidationError({'operator.vat_id': 'ID za DDV vnesite v obliki SI12345678.'})
    result['operator']['vat_id'] = vat
    email = result['operator']['email']
    if email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise ValidationError({'operator.email': 'Vnesite veljaven e-poštni naslov.'})
    size = operator.get('size') or ''
    if size not in ('', *SIZES):
        raise ValidationError({'operator.size': 'Izberite velikost podjetja.'})
    result['operator']['size'] = size
    reps = operator.get('representatives') or []
    if not isinstance(reps, list) or len(reps) > 10:
        raise ValidationError({'operator.representatives': 'Navedete lahko do 10 zastopnikov.'})
    result['operator']['representatives'] = [
        {'name': _text(r.get('name'), 'representative.name', 200), 'role': _text(r.get('role'), 'representative.role', 200)}
        for r in reps if isinstance(r, dict) and (r.get('name') or r.get('role'))]

    part = payload.get('participation') or {}
    if not isinstance(part, dict):
        raise ValidationError({'participation': 'Pričakovan je objekt.'})
    lot_ids = {lot.get('id') for lot in tender.data.get('lots', [])}
    lots = part.get('lots') or []
    if not isinstance(lots, list) or any(lot not in lot_ids for lot in lots):
        raise ValidationError({'participation.lots': 'Izbrani sklop ne obstaja.'})
    result['participation']['lots'] = list(dict.fromkeys(lots))
    for key in ('joint_bid', 'relies_on_others', 'subcontracting'):
        result['participation'][key] = _flag(part.get(key), f'participation.{key}')
    for key in ('joint_partners', 'other_entities', 'subcontractors'):
        result['participation'][key] = _text(part.get(key), f'participation.{key}')

    exclusion = payload.get('exclusion') or {}
    if not isinstance(exclusion, dict):
        raise ValidationError({'exclusion': 'Pričakovan je objekt.'})
    for code, item in exclusion.items():
        if code not in EXCLUSION_CODES or not isinstance(item, dict):
            continue
        answer = item.get('answer')
        if answer not in (None, 'no', 'yes'):
            raise ValidationError({f'exclusion.{code}': 'Odgovor je lahko »da« ali »ne«.'})
        result['exclusion'][code] = {'answer': answer, 'details': _text(item.get('details'), f'exclusion.{code}')}

    selection = payload.get('selection') or {}
    if not isinstance(selection, dict):
        raise ValidationError({'selection': 'Pričakovan je objekt.'})
    result['selection']['global_yes'] = _flag(selection.get('global_yes'), 'selection.global_yes')
    responses = selection.get('responses') or {}
    if not isinstance(responses, dict) or len(responses) > 100:
        raise ValidationError({'selection.responses': 'Pričakovan je objekt odgovorov.'})
    result['selection']['responses'] = {str(k)[:100]: _text(v, 'selection.responses', 4000) for k, v in responses.items() if v is not None}

    final = payload.get('final') or {}
    if not isinstance(final, dict):
        raise ValidationError({'final': 'Pričakovan je objekt.'})
    for key in ('place', 'signatory', 'role'):
        result['final'][key] = _text(final.get(key), f'final.{key}', 200)
    when = final.get('date') or ''
    if when:
        try:
            when = date.fromisoformat(when).isoformat()
        except (TypeError, ValueError):
            raise ValidationError({'final.date': 'Vnesite veljaven datum.'})
    result['final']['date'] = when
    return result


def initial_answers(tender, previous=None):
    """Company-level details carry over from the company's latest ESPD; declarations never do."""
    answers = deepcopy(EMPTY)
    if previous:
        answers['operator'] = deepcopy(previous.get('operator', answers['operator']))
        answers['final']['place'] = previous.get('final', {}).get('place', '')
        answers['final']['signatory'] = previous.get('final', {}).get('signatory', '')
        answers['final']['role'] = previous.get('final', {}).get('role', '')
    return answers


def _money(value):
    return f'{value:,.0f} EUR'.replace(',', '.') if isinstance(value, (int, float)) else None


def _reference_line(ref):
    details = ', '.join(x for x in [str(ref['year']) if ref.get('year') else None, _money(ref.get('value'))] if x)
    line = ref.get('title') or 'Referenca brez naslova'
    if details:
        line += f' ({details})'
    if ref.get('description'):
        line += f': {ref["description"]}'
    return line


def _prefill(req, profile):
    """Suggested Part IV answer from profile facts only, plus the profile evidence used."""
    kind = req.get('kind')
    if kind in ('reference_count', 'reference_value'):
        domain = text_normalize(req.get('domain') or '')
        refs = [r for r in profile.get('references', []) if r.get('confirmed') is True
                and (not domain or text_normalize(r.get('domain', '')) == domain)]
        return '\n'.join(_reference_line(r) for r in refs), [{'type': 'reference', 'id': r.get('id'), 'title': r.get('title')} for r in refs]
    if kind == 'staff' and profile.get('staff_count') is not None:
        text = f'Razpoložljivih strokovnjakov: {profile["staff_count"]}.'
        if profile.get('available_from'):
            text += f' Na voljo od {profile["available_from"]}.'
        return text, [{'type': 'profile', 'id': 'staff_count', 'title': 'Število razpoložljivih strokovnjakov'}]
    if kind == 'certification':
        wanted = certification_key(req.get('certification') or '')
        owned = [c for c in profile.get('certifications', []) if wanted and certification_key(c) == wanted]
        return ('Certifikat: ' + ', '.join(owned) + '.' if owned else ''), [{'type': 'profile', 'id': 'certifications', 'title': c} for c in owned]
    if kind == 'technology':
        wanted = {text_normalize(t) for t in req.get('technologies', [])}
        owned = [t for t in profile.get('technologies', []) if text_normalize(t) in wanted]
        return ('Tehnologije: ' + ', '.join(owned) + '.' if owned else ''), [{'type': 'profile', 'id': 'technologies', 'title': t} for t in owned]
    return '', []


def build_espd(tender, profile, answers, updated_at=None):
    data = tender.data
    meta = data.get('source_metadata') or {}
    registry = profile.get('registry_source') or {}
    is_demo = data.get('source_type') == 'demo'
    status = effective_status(data)

    part1 = {
        'buyer': data.get('buyer') or '',
        'title': data.get('title') or '',
        'notice_number': meta.get('notice_number') or '',
        'source_url': data.get('source_url') or meta.get('url') or '',
        'cpv': data.get('cpv', []),
        'kind': data.get('kind', ''),
        'deadline': data.get('deadline'),
        'lots': [{'id': lot.get('id'), 'title': lot.get('title')} for lot in data.get('lots', [])],
        'source_type': data.get('source_type'),
    }

    origin = 'ajpes' if registry else 'demo' if profile.get('source') == 'demo' else 'profile'
    part2 = [
        {'key': 'name', 'label': 'Naziv', 'value': profile.get('name', ''), 'source': origin if registry.get('name') else 'profile'},
        {'key': 'registration_number', 'label': 'Matična številka', 'value': profile.get('registration_number', ''), 'source': origin if registry.get('registration_number') else 'profile'},
        {'key': 'address', 'label': 'Naslov', 'value': profile.get('address', ''), 'source': origin if registry.get('address') else 'profile'},
        {'key': 'legal_form', 'label': 'Pravnoorganizacijska oblika', 'value': registry.get('legal_form', ''), 'source': 'ajpes' if registry.get('legal_form') else 'missing'},
        {'key': 'registration_authority', 'label': 'Registrski organ', 'value': registry.get('registration_authority', ''), 'source': 'ajpes' if registry.get('registration_authority') else 'missing'},
        {'key': 'website', 'label': 'Spletna stran', 'value': profile.get('website', ''), 'source': 'profile' if profile.get('website') else 'missing'},
    ]

    part4 = []
    for doc in active_documents(tender):
        if doc.status != 'processed' or doc.extraction.get('mode') == 'unprocessed':
            continue
        for req in doc.extraction.get('requirements', []):
            evaluated = evaluate_requirement(req, profile)
            section, section_label = SECTIONS.get(req.get('kind'), ('C', 'Tehnična in strokovna sposobnost'))
            suggestion, evidence = _prefill(req, profile)
            override = answers['selection']['responses'].get(req['id'])
            part4.append({
                'id': req['id'], 'section': section, 'section_label': section_label, 'kind': req.get('kind'),
                'requirement': req.get('title', ''), 'document_id': doc.id, 'page': req.get('page'), 'quote': req.get('quote', ''),
                'status': evaluated['status'], 'company_value': evaluated['company_value'],
                'suggestion': suggestion, 'response': override if override is not None else suggestion,
                'edited': override is not None, 'evidence': evidence,
            })

    warnings = []
    if is_demo:
        warnings.append('Demo razpis: obrazec je primer in ni namenjen oddaji.')
    if status != 'open':
        warnings.append('Razpis ni odprt za prijavo; ESPD je samo za pregled.')
    if not part4:
        warnings.append('Pogoji iz dokumentacije še niso analizirani, zato del IV ni predizpolnjen. Preverite dokumentacijo naročnika.')
    unmet = [row['requirement'] for row in part4 if row['status'] == 'unmet']
    if unmet:
        warnings.append('Po profilu niso izpolnjeni pogoji: ' + '; '.join(unmet) + '. Ne izjavljajte izpolnjevanja brez dokazil.')
    yes_answers = [code for code, item in answers['exclusion'].items() if item.get('answer') == 'yes' and not item.get('details')]
    if yes_answers:
        warnings.append('Pri razlogih za izključitev z odgovorom »da« opišite okoliščine in morebitne ukrepe za dokazovanje zanesljivosti.')

    operator = answers['operator']
    checks = [
        ('ID za DDV', bool(operator['vat_id'])),
        ('Kontaktna oseba', bool(operator['contact_name'])),
        ('E-pošta', bool(operator['email'])),
        ('Velikost podjetja', bool(operator['size'])),
        ('Zastopnik', bool(operator['representatives'])),
        ('Skupna ponudba', answers['participation']['joint_bid'] is not None),
        ('Uporaba zmogljivosti drugih subjektov', answers['participation']['relies_on_others'] is not None),
        ('Podizvajalci', answers['participation']['subcontracting'] is not None),
    ]
    if part1['lots']:
        checks.append(('Izbrani sklopi', bool(answers['participation']['lots'])))
    checks += [(f'Razlog za izključitev: {label}', answers['exclusion'].get(code, {}).get('answer') is not None)
               for group in EXCLUSION_GROUPS for code, label in group['items']]
    checks += [(f'Pogoj: {row["requirement"]}', bool(row['response'].strip())) for row in part4]
    checks += [('Kraj', bool(answers['final']['place'])), ('Datum', bool(answers['final']['date'])), ('Podpisnik', bool(answers['final']['signatory']))]

    return {
        'tender_id': tender.id, 'tender_status': status, 'part1': part1, 'part2': part2,
        'registry': {'attribution': registry.get('attribution'), 'retrieved_at': registry.get('retrieved_at')} if registry else None,
        'part3': [{'code': g['code'], 'title': g['title'], 'items': [{'code': c, 'label': l} for c, l in g['items']]} for g in EXCLUSION_GROUPS],
        'part4': part4, 'answers': answers, 'sizes': SIZES,
        'progress': {'done': sum(ok for _, ok in checks), 'total': len(checks), 'missing': [label for label, ok in checks if not ok]},
        'warnings': warnings, 'updated_at': updated_at.isoformat() if updated_at else None,
    }
