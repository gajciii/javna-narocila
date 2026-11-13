"""Suggested partners for a tender: companies that won similar public contracts.

Source is the PJN award register (``PastAward``). A company is suggested when it was selected in
awards similar to the tender; each win is a public, verifiable reference. Suggestions never change
the company's partners until the user adds one explicitly.
"""
import logging
from collections import defaultdict
from datetime import date

from django.db import transaction

from .award_references import identity, reference
from .deep_relevance import fold
from .models import PastAward, Partner
from .seed import today

log = logging.getLogger(__name__)

SUGGESTIONS = 6
WINS_SHOWN = 4
MAX_REFERENCES = 30


def similar_pool(tender):
    """[(similarity, award)] of awards similar to the tender, above the shown-result thresholds."""
    from .past_awards import TEXT_THRESHOLD, VECTOR_THRESHOLD, fused_candidates, index, vector_candidates
    idx = index()
    if not idx['awards']:
        return []
    try:
        semantic = vector_candidates(tender.data)
    except Exception as exc:  # The provider or index being unavailable must not hide word matches.
        log.warning('Vector candidates unavailable: %s', type(exc).__name__)
        semantic = []
    found, similarity = fused_candidates(tender.data, idx, semantic)
    return [(score, award) for score, award in found
            if score >= (VECTOR_THRESHOLD if award.pk in similarity else TEXT_THRESHOLD)]


def win(score, award):
    d = award.data
    euro = d.get('currency') in (None, 'EUR')
    return {'award_id': award.pk, 'title': d.get('title', ''), 'lot_title': d.get('lot_title', ''),
            'buyer': d.get('buyer', ''), 'published_on': award.published_on.isoformat() if award.published_on else None,
            'value': d.get('awarded_value') if euro else None, 'joint': len(d.get('winners') or []) > 1,
            'similarity': round(score, 2), 'notice_url': f'https://www.enarocanje.si/#/pregled-objav/{award.notice_id}'}


def reference_gaps(missing):
    """Open conditions that public award references can help with."""
    return [c['title'] for c in missing
            if (c.get('check') or {}).get('kind') in ('reference_count', 'reference_value')
            or 'referenc' in fold(f"{c.get('title', '')} {c.get('requirement', '')}")]


def partner_numbers(company):
    from .improvements import company_key
    rows = Partner.objects.filter(company_key=company_key(company)).values_list('pk', 'data')
    return {identity(data.get('registration_number')): pk for pk, data in rows if data.get('registration_number')}


def suggestions(tender):
    from .partners import condition_set
    from .documents import active_documents
    from .seed import get_profile
    company = get_profile()
    base = {'tender_id': tender.pk, 'items': [], 'message': '', 'reference_gaps': [],
            'source': 'Portal javnih naročil, obvestila o oddaji (CC BY 4.0)'}
    if tender.data.get('source_type') != 'real':
        return {**base, 'message': 'Predloge partnerjev pripravimo samo za resnične objave.'}
    from .matching import effective_status
    if effective_status(tender.data) != 'open':
        return {**base, 'message': 'Partnerje predlagamo za odprte razpise.'}
    pool = similar_pool(tender)
    if not pool:
        return {**base, 'message': 'V zbirki preteklih oddaj ni dovolj podobnih naročil za predlog partnerjev.'}
    conditions = condition_set(tender, company, active_documents(tender))
    base['reference_gaps'] = reference_gaps([c for c in conditions['items'] if c['status'] != 'met'])
    own = identity(company.get('registration_number'))
    existing = partner_numbers(company)
    companies = defaultdict(lambda: {'name': '', 'wins': [], 'score': 0.0})
    for score, award in pool:
        if not award.data.get('awarded'):
            continue
        for winner in award.data.get('winners') or []:
            number = identity(winner.get('registration_number'))
            # Without a registration number the company cannot be identified or looked up in AJPES.
            if not number or number == own:
                continue
            entry = companies[number]
            entry['name'] = entry['name'] or winner.get('name', '')
            entry['wins'].append(win(score, award))
            entry['score'] += score
    items = []
    for number, entry in companies.items():
        wins = sorted(entry['wins'], key=lambda w: -w['similarity'])
        latest = max((w['published_on'] for w in wins if w['published_on']), default=None)
        recency = 0.1 if latest and date.fromisoformat(latest).year >= today().year - 2 else 0.0
        items.append({'registration_number': number, 'name': entry['name'], 'wins_count': len(wins),
                      'total_value': sum(w['value'] for w in wins if w['value']) or None,
                      'latest_win': latest, 'joint_bids': sum(w['joint'] for w in wins),
                      'wins': wins[:WINS_SHOWN], 'partner_id': existing.get(number),
                      'rank': entry['score'] + recency})
    items.sort(key=lambda i: (-i['rank'], -i['wins_count'], i['name']))
    for item in items:
        item.pop('rank')
    base['items'] = items[:SUGGESTIONS]
    if not base['items']:
        base['message'] = 'Podobna naročila so bila oddana samo vašemu podjetju ali izvajalcem brez matične številke.'
    return base


def award_references(number):
    """Public award references of the company with this registration number, newest first."""
    awards = PastAward.objects.filter(data__winners__icontains=number, data__awarded=True).order_by('-published_on', 'pk')
    refs = []
    for award in awards:
        if any(identity(w.get('registration_number')) == number for w in award.data.get('winners') or []):
            refs.append(reference(award))
        if len(refs) == MAX_REFERENCES:
            break
    return refs


@transaction.atomic
def add_suggested_partner(number):
    """Create a partner from AJPES basic data and the company's public award references."""
    from rest_framework.exceptions import ValidationError
    from .ajpes import RegistryUnavailable, preview
    from .improvements import company_key
    from .partners import partner_values
    number = identity(number if isinstance(number, str) else '')
    if not number.isdigit() or len(number) != 10:
        raise ValidationError('Neveljavna matična številka.')
    refs = award_references(number)
    if not refs:
        raise ValidationError('To podjetje ni med izbranimi ponudniki v zbirki preteklih oddaj.')
    try:
        profile = preview(number)['profile']
    except (LookupError, RegistryUnavailable):
        # AJPES lists only active companies and may be offline; the award notice still names the winner.
        award = PastAward.objects.filter(data__winners__icontains=number, data__awarded=True).order_by('-published_on').first()
        name = next(w.get('name', '') for w in award.data['winners'] if identity(w.get('registration_number')) == number)
        profile = {'name': name, 'registration_number': number}
    profile = {key: profile.get(key, '') for key in ('name', 'registration_number', 'address')}
    profile['references'] = refs
    values = partner_values({'source_type': 'real', 'profile': profile,
                             'capability_evidence': {'source': '', 'url': '', 'confirmed': False}})
    return Partner.objects.create(company_key=company_key(), **values)
