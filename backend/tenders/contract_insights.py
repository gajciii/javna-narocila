"""Signed contracts as decision support: who holds a buyer's related contract, and which contracts
are about to expire and may be tendered again. Descriptive only; never a promise of a new tender."""
import re
import unicodedata
from datetime import timedelta

from django.db.models import Count, Max, Min
from rest_framework.exceptions import ValidationError

from .models import Contract, ContractSyncState
from .pjn_contracts import buyer_key, cpv_groups, tender_buyer_registrations
from .pjn_normalize import SOURCE
from .seed import today

PAGE_SIZE = 20
MONTHS = (3, 6, 12, 24)
INCUMBENT_LIMIT = 12


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).lower()) if not unicodedata.combining(c))


def stems(value):
    """Six-letter prefixes of words with at least four letters, so inflected Slovenian forms meet."""
    return {word[:6] for word in re.findall(r'[a-z0-9]+', fold(value)) if len(word) >= 4 and not word.isdigit()}


def shared_cpv(code, others):
    return max((n for other in others for n in (8, 5, 4, 3) if code and other and code[:n] == other[:n]), default=0)


def status(contract, on):
    if contract.effective_end is None:
        return 'unknown'
    return 'active' if contract.effective_end >= on else 'ended'


def serialize(contract, on):
    d = contract.data
    end = contract.effective_end
    return {'id': contract.pk, 'title': d.get('title') or d.get('procurement_title') or 'Pogodba',
            'procurement_title': d.get('procurement_title') or '',
            'buyer': '; '.join(b['name'] for b in d.get('buyers') or []), 'buyer_registration': contract.buyer_registration,
            'contractors': d.get('contractors') or [], 'cpv': contract.cpv, 'cpv_label': d.get('cpv_label') or '',
            'kind': d.get('kind') or '', 'framework': bool(d.get('framework')), 'value': d.get('value'),
            'concluded_on': d.get('concluded_on'), 'valid_from': d.get('valid_from'), 'valid_to': d.get('valid_to'),
            'effective_end': end.isoformat() if end else None,
            'extended': bool(end and contract.valid_to and end > contract.valid_to),
            'addenda_count': contract.addenda_count, 'days_left': (end - on).days if end else None,
            'status': status(contract, on), 'notice_number': d.get('notice_number') or '',
            'procurement_number': d.get('procurement_number') or '', 'files': (d.get('files') or [])[:2]}


def dataset_info():
    stats = Contract.objects.filter(is_addendum=False).aggregate(
        contracts=Count('pk'), first=Min('published_at'), last=Max('published_at'))
    state = ContractSyncState.objects.filter(pk='list').first()
    return {'attribution': SOURCE, 'contracts': stats['contracts'],
            'with_end': Contract.objects.filter(is_addendum=False, effective_end__isnull=False).count(),
            'coverage_from': stats['first'].date().isoformat() if stats['first'] else None,
            'coverage_to': stats['last'].date().isoformat() if stats['last'] else None,
            'register_synced_until': state.synced_until.isoformat() if state and state.synced_until else None}


# --- Feature: current contractor of a tender's buyer --------------------------------------------

def incumbents(tender):
    on = today()
    base = {'mode': 'empty', 'headline': None, 'results': [], 'buyers': [], 'synced_at': None,
            'complete': False, 'message': '', 'dataset': dataset_info()}
    if tender.data.get('source_type') != 'real':
        return {**base, 'message': 'Pogodbe naročnika so na voljo pri resničnih objavah.'}
    registrations = tender_buyer_registrations(tender)
    codes = [c for c in tender.data.get('cpv') or [] if isinstance(c, str)]
    groups = cpv_groups(codes)
    base['buyers'] = registrations
    if not registrations:
        return {**base, 'message': 'Naročnik nima matične številke; pogodb ne povezujemo samo po imenu.'}
    if not groups:
        return {**base, 'message': 'Razpis nima CPV kode, zato sorodnih pogodb ni mogoče izbrati.'}
    states = list(ContractSyncState.objects.filter(pk__in=[buyer_key(r, groups) for r in registrations[:2]]))
    synced = [s.synced_at for s in states if s.synced_at]
    base['synced_at'] = min(synced).isoformat() if synced and len(synced) == len(registrations[:2]) else None
    base['complete'] = base['synced_at'] is not None
    own = tender.data.get('source_metadata', {}).get('dossier_id')
    rows = []
    for contract in Contract.objects.filter(is_addendum=False, buyer_registration__in=registrations):
        level = shared_cpv(contract.cpv, codes)
        # The tender's own result is not an incumbent.
        if level and not (own and contract.dossier_id == own):
            rows.append((contract, level))
    order = {'active': 0, 'unknown': 1, 'ended': 2}
    # Newest first, then (stable) active before ended and closer CPV before broader.
    rows.sort(key=lambda r: (r[0].data.get('concluded_on') or '', r[0].pk), reverse=True)
    rows.sort(key=lambda r: (order[status(r[0], on)], -r[1]))
    if not rows:
        message = ('Pri tem naročniku ni zbranih pogodb s sorodnim CPV.' if base['complete'] else
                   'Pogodbe naročnika s sorodnim CPV še niso zajete. Osvežite pogodbe naročnika.')
        return {**base, 'message': message}
    headline = None
    active = [r for r in rows if status(r[0], on) == 'active']
    pool, kind = (active, 'active') if active else ([r for r in rows if status(r[0], on) == 'ended'], 'recent')
    if pool:
        best = pool[0][1]
        chosen = [c for c, level in pool if level == best][:5]
        contractors = {}
        for contract in chosen:
            for party in contract.data.get('contractors') or []:
                key = party.get('registration_number') or fold(party.get('name'))
                entry = contractors.setdefault(key, {**party, 'contracts': 0})
                entry['contracts'] += 1
        headline = {'kind': kind, 'cpv_level': best, 'contractors': sorted(contractors.values(), key=lambda p: -p['contracts']),
                    'end': max((c.effective_end for c in chosen if c.effective_end), default=None)}
        headline['end'] = headline['end'].isoformat() if headline['end'] else None
    results = [{**serialize(c, on), 'cpv_level': level} for c, level in rows[:INCUMBENT_LIMIT]]
    return {**base, 'mode': 'data', 'headline': headline, 'results': results, 'total': len(rows)}


# --- Feature: contracts that expire soon and match the company profile ----------------------------

def profile_terms(profile, extra=''):
    terms = {}
    for value in list(profile.get('keywords') or []) + list(profile.get('expertise') or []) + (extra or '').split(','):
        value = ' '.join(str(value).split())
        if value and stems(value):
            terms.setdefault(fold(value), value)
    return terms


def expected_options(params):
    try:
        months = int(params.get('months', '12'))
    except (TypeError, ValueError):
        months = 0
    if months not in MONTHS:
        raise ValidationError({'months': 'Izberite 3, 6, 12 ali 24 mesecev.'})
    cpv = (params.get('cpv') or '').strip()
    if cpv and not re.fullmatch(r'\d{2,8}', cpv):
        raise ValidationError({'cpv': 'Vnesite od 2 do 8 začetnih števk CPV.'})
    terms = params.get('terms') or ''
    if len(terms) > 500:
        raise ValidationError({'terms': 'Vnesite največ 500 znakov.'})
    page = params.get('page', '1')
    if not isinstance(page, str) or not re.fullmatch(r'\d{1,4}', page) or int(page) < 1:
        raise ValidationError({'page': 'Neveljavna stran.'})
    return {'months': months, 'cpv': cpv, 'terms': terms, 'page': int(page)}


def expected_tenders(profile, params):
    options = expected_options(params)
    on = today()
    terms = profile_terms(profile, options['terms'])
    base = {'mode': 'empty', 'months': options['months'], 'terms': list(terms.values()), 'cpv': options['cpv'],
            'results': [], 'count': 0, 'page': options['page'], 'page_size': PAGE_SIZE,
            'dataset': dataset_info(), 'message': ''}
    if not terms and not options['cpv']:
        return {**base, 'mode': 'profile_missing',
                'message': 'Profil nima ključnih besed ali strokovnih področij. Dopolnite profil ali vnesite področje CPV.'}
    term_stems = {key: stems(value) for key, value in terms.items()}
    end = on + timedelta(days=round(30.44 * options['months']))
    candidates = Contract.objects.filter(is_addendum=False, effective_end__gte=on, effective_end__lte=end)
    if options['cpv']:
        candidates = candidates.filter(cpv__startswith=options['cpv'])
    matches = []
    for contract in candidates.order_by('effective_end', 'pk'):
        d = contract.data
        words = stems(' '.join([d.get('title') or '', d.get('procurement_title') or '', d.get('cpv_label') or '']))
        matched = [terms[key] for key, needed in term_stems.items() if needed <= words]
        if matched or not terms:
            matches.append((contract, matched))
    start = (options['page'] - 1) * PAGE_SIZE
    results = []
    for contract, matched in matches[start:start + PAGE_SIZE]:
        item = serialize(contract, on)
        item['matched_terms'] = matched
        item['newer_contract'] = newer_related(contract)
        results.append(item)
    message = '' if matches else 'V izbranem obdobju ni pogodb, ki bi potekle in se ujemale s profilom.'
    return {**base, 'mode': 'data' if matches else 'empty', 'results': results, 'count': len(matches), 'message': message}


def newer_related(contract):
    """A later contract of the same buyer and CPV category suggests the need may already be covered."""
    if not contract.buyer_registration or not contract.cpv or not contract.published_at:
        return None
    newer = (Contract.objects.filter(is_addendum=False, buyer_registration=contract.buyer_registration,
                                     cpv__startswith=contract.cpv[:5], published_at__gt=contract.published_at)
             .exclude(pk=contract.pk))
    if contract.dossier_id:
        newer = newer.exclude(dossier_id=contract.dossier_id)
    found = newer.order_by('-published_at').first()
    if not found:
        return None
    return {'id': found.pk, 'title': found.data.get('title') or '', 'concluded_on': found.data.get('concluded_on'),
            'contractors': [p['name'] for p in found.data.get('contractors') or []][:3]}
