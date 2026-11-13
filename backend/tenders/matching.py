from .accounts import following as account_following, ignored as account_ignored
import re
import unicodedata
import math
from datetime import datetime
from django.utils import timezone
from django.conf import settings
from .documents import active_documents, serialize_document
from .seed import today


def text_normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).lower()) if not unicodedata.combining(c))


def certification_key(value):
    value = text_normalize(value).strip()
    value = re.sub(r'iso\s*(?:/\s*)?iec\s*', 'iso ', value)
    return re.sub(r'[\s-]+', '', value)


def certification_needs_review(req):
    text = text_normalize(req.get('quote', '') + ' ' + req.get('certification', ''))
    return bool(req.get('requires_manual_review') or re.search(r'\b(?:19|20)\d{2}\b|enakovred|veljav|obseg|akredit|equivalent|scope|valid|\bali\b|\bor\b|za podroc', text))


GROUPS = {
    'software': ['programsk', 'spletn', 'aplikacij', 'software', 'web', 'portal', 'informacijsk', 'react', 'django', 'vue', 'asp.net'],
    'iot': ['iot', 'senzor', 'integracij', 'digitalni dvoj', 'spremljanje', 'avtomatizacij', 'websocket'],
    'data': ['podatkov', 'analitik', 'analiz', 'satelit', 'umetna inteligenca', ' ai ', 'machine learning'],
    'construction': ['gradben', 'gradnja', 'novograd', 'izgradnj', 'rekonstruk', 'sanacij', 'gradnje'],
    'supply': ['dobava', 'prodaja', 'trgovina', 'licenc', 'distribucij'],
    'cybersecurity': ['kibernetsk', 'cybersecurity', 'penetracijsk', 'informacijska varnost'],
}


def categories(text):
    text = ' ' + text_normalize(text) + ' '
    return {category for category, terms in GROUPS.items() if any(term in text for term in terms)}


def content_match(data, profile):
    expertise = profile.get('expertise', []) + profile.get('keywords', [])
    company_text = ' '.join([profile.get('description', ''), profile.get('activity', '')] + expertise)
    company_categories = categories(company_text)
    tender_text = ' '.join(data.get('topics', []))
    real_source = data.get('source_type') == 'real'
    # Imported topics are CPV labels, including broad category descriptions.
    # Only the actual subject may establish a strong content match.
    subject = ' '.join([data.get('title', ''), data.get('summary', '')])
    tender_categories = categories(subject if real_source else tender_text or data.get('summary', ''))
    cpv_overlap = categories(tender_text) & company_categories if real_source else set()
    overlap = company_categories & tender_categories
    tech = sorted(set(map(text_normalize, profile.get('technologies', []))) & set(map(text_normalize, data.get('technologies', []))))
    if tender_categories:
        score = round(20 + 65 * len(overlap) / len(tender_categories) + min(10, len(tech) * 3))
    else:
        score = 35
    matched_topics = [topic for topic in data.get('topics', []) if categories(topic) & company_categories or any(text_normalize(topic) in text_normalize(k) for k in expertise)] if not real_source else []
    if not overlap and not tech:
        score = 45 if cpv_overlap else 18
    if data.get('kind') == 'goods' and 'supply' not in company_categories:
        score = min(score, 25)
    if data.get('kind') == 'works' and 'construction' not in company_categories:
        score = min(score, 25)
    score = max(0, min(score, 99))
    level = 'high' if score >= 70 else 'medium' if score >= 40 else 'low'
    reasons = []
    if real_source and overlap:
        reasons.append('Naslov in opis naročila se vsebinsko ujemata z opisanimi dejavnostmi podjetja.')
    elif real_source and cpv_overlap:
        reasons.append('Ujema se širša CPV kategorija; konkretna storitev zahteva dodatno vsebinsko presojo.')
    if matched_topics:
        reasons.append('Predmet se ujema s področji podjetja: ' + ', '.join(matched_topics[:3]) + '.')
    if tech:
        originals = {text_normalize(x): x for x in data.get('technologies', [])}
        reasons.append('Ujemanje tehnologij: ' + ', '.join(originals[x] for x in tech[:4]) + '.')
    if level == 'low':
        reasons = ['Predmet naročila se slabo ujema z opisanimi dejavnostmi podjetja.']
        if data.get('kind') == 'goods':
            reasons.append('Poudarek je na dobavi, profil podjetja pa opisuje razvoj in izvedbo rešitev.')
        elif data.get('kind') == 'works' and 'construction' not in company_categories:
            reasons.append('Naročilo je namenjeno gradbenim delom, profil pa ne navaja gradbenih dejavnosti.')
    if not reasons:
        reasons = ['Za natančnejšo vsebinsko presojo dopolnite profil podjetja.']
    if len(reasons) == 1:
        reasons.append('Končna presoja je odvisna od pogojev in dokazil iz dokumentacije.')
    return level, score, reasons[:2]


def evaluate_requirement(req, profile):
    result = {'id': req['id'], 'title': req['title'], 'company_value': 'Podatek ni vnesen.',
              'status': 'unknown', 'document_id': req.get('document_id'), 'page': req.get('page'), 'quote': req.get('quote', '')}
    kind = req.get('kind')
    minimum = req.get('minimum', 1)
    if kind not in ('technology', 'certification') and (isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum)):
        result['company_value'] = 'Prag pogoja ni dovolj jasno določen.'
        return result
    if kind in ('reference_count', 'reference_value'):
        refs = [r for r in profile.get('references', []) if not req.get('domain') or text_normalize(r.get('domain', '')) == text_normalize(req['domain'])]
        # A project identifier denotes one project even when entered more than once.
        projects, anonymous = {}, []
        for ref in refs:
            project = text_normalize(ref.get('project_identifier', '')).strip()
            if not project:
                anonymous.append(ref)
            elif project not in projects:
                projects[project] = dict(ref)
            elif any(projects[project].get(k) != ref.get(k) for k in ('domain', 'value', 'year', 'confirmed')):
                projects[project]['confirmed'] = False
        refs = anonymous + list(projects.values())
        confirmed = [r for r in refs if r.get('confirmed') is True]
        valid, uncertain = [], []
        for ref in confirmed:
            if ref.get('year') is not None and ref['year'] > today().year:
                continue
            if req.get('max_age_years'):
                year = ref.get('year')
                if year is None:
                    uncertain.append(ref)
                    continue
                if year == today().year - req['max_age_years']:
                    uncertain.append(ref)
                    continue
                if not (today().year - req['max_age_years'] < year <= today().year):
                    continue
            valid.append(ref)
        if kind == 'reference_count':
            result['company_value'] = f'{len(valid)} potrjenih ustreznih referenc' + (f'; {len(uncertain)} brez datuma zaključka' if uncertain else '')
            if len(valid) >= minimum:
                result['status'] = 'met'
            elif len(valid) + len(uncertain) + len(refs) - len(confirmed) >= minimum or not profile.get('references'):
                result['status'] = 'unknown'
            else:
                result['status'] = 'unmet'
        else:
            values = [r['value'] for r in valid if r.get('value') is not None]
            known_max = max(values, default=None)
            missing = uncertain or any(r.get('value') is None for r in valid) or len(refs) > len(confirmed)
            result['company_value'] = f'Najvišja potrjena vrednost: {known_max:,.0f} EUR'.replace(',', '.') if known_max is not None else 'Manjka vrednost ali datum zaključka primerljive reference.'
            if known_max is not None and known_max >= minimum:
                result['status'] = 'met'
            elif missing or not refs:
                result['status'] = 'unknown'
            else:
                result['status'] = 'unmet'
    elif kind == 'certification':
        certificate = req.get('certification')
        if not certificate or certification_needs_review(req):
            result['company_value'] = 'Preverite različico, veljavnost, obseg ali enakovrednost certifikata v dokazilih.'
        elif certification_key(certificate) in {certification_key(c) for c in profile.get('certifications', [])}:
            result.update(company_value=f'V profilu naveden certifikat: {certificate}.', status='met')
        else:
            result['company_value'] = f'Certifikat {certificate} ni naveden v profilu; preverite, ali ga podjetje že ima.'
    elif kind == 'staff':
        count = profile.get('staff_count')
        if count is not None:
            result.update(company_value=f'{count} razpoložljivih sodelavcev', status='met' if count >= minimum else 'unmet')
    elif kind == 'technology':
        company = {text_normalize(x) for x in profile.get('technologies', [])}
        required = {text_normalize(x) for x in req.get('technologies', [])}
        if company and required:
            match = company & required
            status = 'met' if required.issubset(company) else 'unknown' if match else 'unmet'
            company_value = ', '.join(profile['technologies'])
            if status == 'unknown':
                company_value += '; preverite, ali so zahtevane vse tehnologije ali dovoljena alternativa.'
            result.update(company_value=company_value, status=status)
    return result


def effective_status(data):
    if data.get('status') != 'open':
        return data.get('status', 'closed')
    try:
        dt = datetime.fromisoformat(data['deadline'].replace('Z', '+00:00'))
        if dt.date() < today():
            return 'closed'
        if not settings.DEMO_DATE and dt.tzinfo and dt <= timezone.now():
            return 'closed'
    except (KeyError, ValueError, TypeError):
        pass
    return 'open'


def serialize_tender(tender, profile, documents=None, content_result=None, unmet_condition=None):
    """``unmet_condition`` is the title of a tender condition the company marked as not met."""
    data = dict(tender.data)
    docs = active_documents(tender, metadata_only=True) if documents is None else documents
    requirements = [req for doc in docs if doc.status == 'processed' and doc.extraction.get('mode') != 'unprocessed' for req in doc.extraction.get('requirements', [])]
    conditions = [evaluate_requirement(req, profile) for req in requirements]
    if content_result is None:
        from .relevance import resolve_matches
        content_result = resolve_matches([tender], profile)[tender.pk]
    level, score, reasons = content_match(data, profile)
    if content_result.get('mode') == 'gemini':
        level, score, reasons = content_result['level'], content_result['score'], content_result['reasons']
    status = effective_status(data)
    has_unknown = any(c['status'] == 'unknown' for c in conditions)
    has_unmet = any(c['status'] == 'unmet' for c in conditions)
    if status == 'unconfirmed':
        recommendation = 'review'
        open_question = 'Stanje in rok za prijavo nista potrjena. Preverite izvorno objavo.'
    elif status != 'open':
        recommendation = 'closed'
        open_question = 'Naročilo ni odprto za prijavo.'
    elif level == 'low' or has_unmet or unmet_condition:
        recommendation = 'unsuitable'
        open_question = next((c['title'] for c in conditions if c['status'] == 'unmet'),
                             f'Pogoja »{unmet_condition}« po vaši oznaki v profilu ne izpolnjujete.' if unmet_condition
                             else 'Predmet ni med glavnimi dejavnostmi podjetja.')
    elif not conditions or has_unknown or any(d.status != 'processed' or d.extraction.get('mode') == 'unprocessed' or d.extraction.get('rejected_requirements', 0) for d in docs):
        recommendation = 'review'
        open_question = next((c['company_value'] for c in conditions if c['status'] == 'unknown'), 'Pogoji iz celotne dokumentacije še niso preverjeni.')
    else:
        recommendation = 'recommended' if level == 'high' else 'review'
        open_question = 'Preverite dokazila in razpoložljivost ekipe pred odločitvijo.'
    lots = []
    for lot in data.get('lots', []):
        lot_level, _, _ = content_match({**data, 'title': lot['title'], 'topics': lot.get('topics', []), 'summary': lot['summary'], 'technologies': [], 'kind': lot.get('kind') or ('goods' if 'oprem' in text_normalize(lot['title']) else 'services')}, profile)
        lots.append({**lot, 'match_level': lot_level})
    criteria = next((doc.extraction['criteria'] for doc in docs if doc.extraction.get('criteria')), data.get('criteria', []))
    preference_notes = []
    value = data.get('value')
    if value is not None and profile.get('min_value') is not None and value < profile['min_value']:
        preference_notes.append('Vrednost je pod želenim obsegom projektov.')
    if value is not None and profile.get('max_value') is not None and value > profile['max_value']:
        preference_notes.append('Vrednost presega želeni obseg projektov.')
    company_regions = profile.get('regions', [])
    if company_regions and 'Slovenija' not in company_regions and data.get('region') not in company_regions:
        preference_notes.append('Lokacija ni med izbranimi regijami podjetja.')
    if any(text_normalize(word) in text_normalize(data.get('title', '') + ' ' + data.get('summary', '')) for word in profile.get('excluded_keywords', [])):
        preference_notes.append('Predmet vsebuje izraz, ki ga podjetje želi izključiti; preverite kontekst.')
    if preference_notes:
        reasons = [reasons[0], preference_notes[0]]
        if recommendation == 'recommended':
            recommendation = 'review'
        if not has_unknown and not has_unmet and status == 'open':
            open_question = preference_notes[0]
    return {**data, 'id': tender.pk, 'status': status, 'following': account_following(tender), 'ignored': account_ignored(tender), 'criteria': criteria, 'lots': lots,
            'documents': [serialize_document(doc) for doc in docs], 'preference_notes': preference_notes,
            'match': {'level': level, 'score': score, 'mode': content_result.get('mode', 'rules'),
                      'warning': content_result.get('warning'), 'recommendation': recommendation, 'reasons': reasons,
                      'open_question': open_question, 'conditions': conditions}}
