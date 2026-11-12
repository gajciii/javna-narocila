"""Descriptive buyer history. No probabilistic accusation or AI-generated evidence."""
import re
from collections import defaultdict
from datetime import date

from django.db.models import Q
from rest_framework.exceptions import ValidationError

from .models import PastAward
from .past_awards import clean, dataset_info, number, registration, serialize

PAGE_SIZE = 20


def identity(value):
    value = registration(value)
    return value + '000' if len(value) == 7 else value


def name_key(value):
    return clean(value).casefold()


def buyer_options(tender):
    buyers = tender.data.get('source_metadata', {}).get('buyers') or []
    return [{'name': b['name'], 'registration_number': identity(b.get('registration_number'))}
            for b in buyers if b.get('name')] or [
        {'name': name.strip(), 'registration_number': ''}
        for name in tender.data.get('buyer', '').split(';') if name.strip()]


def latest_lots(rows):
    # Equal titles alone cannot establish a correction: frameworks may have repeated awards.
    # Only explicit predecessor links and matching lot names supersede an older record.
    by_notice = defaultdict(list)
    for row in rows:
        by_notice[row.notice_id].append(row)
    superseded = set()
    for row in rows:
        previous = row.data.get('previous_notice_id')
        if not previous or str(previous) == row.notice_id:
            continue
        lot = name_key(row.data.get('lot_title') or row.data.get('title'))
        for old in by_notice.get(str(previous), []):
            if lot and lot == name_key(old.data.get('lot_title') or old.data.get('title')):
                superseded.add(old.pk)
    return [r for r in rows if r.pk not in superseded]


def winners(row):
    result = {}
    for winner in row.data.get('winners') or []:
        name = clean(winner.get('name'), 300)
        if not name:
            continue
        reg = identity(winner.get('registration_number'))
        key = 'id:' + reg if reg else 'name:' + name_key(name)
        result[key] = {'key': key, 'name': name, 'registration_number': reg}
    return list(result.values())


def eligible_value(row, selected_winners):
    d = row.data
    if d.get('framework') or len(selected_winners) != 1 or d.get('currency') != 'EUR':
        return None
    return number(d.get('awarded_value'))


def options(params):
    result = {}
    for key in ('from', 'to'):
        value = params.get(key, '')
        try:
            result[key] = date.fromisoformat(value) if value else None
        except (ValueError, TypeError):
            raise ValidationError({key: 'Vnesite datum v obliki YYYY-MM-DD.'})
    if result['from'] and result['to'] and result['from'] > result['to']:
        raise ValidationError('Začetni datum mora biti pred končnim.')
    result['cpv'] = params.get('cpv', '').strip()
    if result['cpv'] and not re.fullmatch(r'\d{2,8}', result['cpv']):
        raise ValidationError({'cpv': 'Vnesite od 2 do 8 začetnih števk CPV.'})
    for key, default in (('buyer', '0'), ('page', '1')):
        value = params.get(key, default)
        if not isinstance(value, str) or not re.fullmatch(r'\d{1,6}', value):
            raise ValidationError({key: 'Neveljavna izbira.'})
        result[key] = int(value)
    if result['page'] < 1:
        raise ValidationError({'page': 'Neveljavna stran.'})
    result['supplier'] = params.get('supplier', '')
    if len(result['supplier']) > 350:
        raise ValidationError({'supplier': 'Neveljaven prejemnik.'})
    return result


def history(tender, params):
    filters = options(params)
    buyers = buyer_options(tender)
    base = {'buyers': buyers, 'buyer_index': filters['buyer'], 'buyer': None,
            'dataset': dataset_info(), 'suppliers': [], 'summary': None, 'signals': [],
            'results': [], 'history_count': 0, 'page': filters['page'], 'page_size': PAGE_SIZE,
            'mode': 'empty', 'message': ''}
    if tender.data.get('source_type') != 'real':
        return {**base, 'message': 'Zgodovina naročnika je na voljo pri resničnih objavah.'}
    if not buyers or filters['buyer'] >= len(buyers):
        raise ValidationError({'buyer': 'Naročnik ni prepoznan.'})
    buyer = buyers[filters['buyer']]
    base['buyer'] = buyer
    reg, name = buyer['registration_number'], buyer['name']
    named = list(PastAward.objects.filter(data__buyer__iexact=name))
    named_ids = {identity(r.data.get('buyer_registration_number')) for r in named} - {''}
    if not reg and len(named_ids) > 1:
        return {**base, 'mode': 'ambiguous', 'message': 'Ime naročnika se pojavlja z več matičnimi številkami. Podatkov ne združujemo; najprej osvežite izvorne podatke razpisa.'}
    reg = reg or next(iter(named_ids), '')
    if reg:
        variants = [reg, reg[:7]] if len(reg) == 10 and reg.endswith('000') else [reg]
        rows = list(PastAward.objects.filter(Q(data__buyer_registration_number__in=variants) |
            Q(data__buyer__iexact=name, data__buyer_registration_number='')))
    else:
        rows = named
    base['buyer'] = {**buyer, 'registration_number': reg, 'matched_by': 'registration_number' if reg else 'name'}
    selected = latest_lots(rows)
    duplicates = len(rows) - len(selected)
    def in_scope(row):
        if filters['from'] or filters['to']:
            if not row.published_on or (filters['from'] and row.published_on < filters['from']) or (filters['to'] and row.published_on > filters['to']):
                return False
        return not filters['cpv'] or any(code.startswith(filters['cpv']) for code in row.data.get('cpv') or [])
    selected = [r for r in selected if in_scope(r)]
    awarded = [r for r in selected if r.data.get('awarded') and winners(r)]
    suppliers = {}
    known_bids = single_bid = value_count = joint_count = framework_count = 0
    total_value = 0
    for row in awarded:
        ws = winners(row)
        d = row.data
        bids = d.get('tenders_received')
        bids_known = isinstance(bids, int) and not isinstance(bids, bool) and bids > 0
        known_bids += bids_known
        single_bid += bids_known and bids == 1
        joint_count += len(ws) > 1
        framework_count += bool(d.get('framework'))
        value = eligible_value(row, ws)
        if value is not None:
            value_count += 1
            total_value += value
        for w in ws:
            entry = suppliers.setdefault(w['key'], {**w, 'wins': 0, 'sole_wins': 0, 'joint_wins': 0,
                'value_eur': 0, 'value_count': 0, 'single_bid_wins': 0})
            entry['wins'] += 1
            entry['sole_wins'] += len(ws) == 1
            entry['joint_wins'] += len(ws) > 1
            entry['single_bid_wins'] += bids_known and bids == 1
            if value is not None:
                entry['value_eur'] += value
                entry['value_count'] += 1
    count = len(awarded)
    ranking = sorted(suppliers.values(), key=lambda s: (-s['wins'], -s['value_eur'], s['name']))
    for entry in ranking:
        entry.update(share=entry['wins'] / count if count else None,
                     value_eur=round(entry['value_eur'], 2),
                     value_share=entry['value_eur'] / total_value if total_value else None)
    signals = []
    if count < 10:
        signals.append({'kind': 'sample', 'text': 'Manj kot 10 oddanih sklopov: vzorec je majhen za presojo koncentracije.'})
    if count >= 10 and ranking and ranking[0]['share'] >= .5:
        signals.append({'kind': 'concentration', 'text': f"{ranking[0]['name']} nastopa pri vsaj polovici oddanih sklopov ({ranking[0]['wins']}/{count}), tudi v skupnih ponudbah."})
    if known_bids >= 10 and single_bid / known_bids >= .5:
        signals.append({'kind': 'competition', 'text': f'Vsaj polovica oddaj z znanim številom ponudb ima eno samo ponudbo ({single_bid}/{known_bids}).'})
    dated = [r.published_on for r in selected if r.published_on]
    summary = {'lots': len(selected), 'awarded_lots': count, 'not_awarded_lots': len(selected) - count,
        'supplier_count': len(ranking), 'known_bid_lots': known_bids, 'single_bid_lots': single_bid,
        'single_bid_share': single_bid / known_bids if known_bids else None,
        'total_value_eur': round(total_value, 2), 'value_lots': value_count,
        'joint_lots': joint_count, 'framework_lots': framework_count,
        'excluded_value_lots': count - value_count, 'superseded_lots': duplicates,
        'undated_lots': sum(r.published_on is None for r in selected),
        'coverage_from': min(dated).isoformat() if dated else None,
        'coverage_to': max(dated).isoformat() if dated else None}
    history_rows = [r for r in selected if not filters['supplier'] or
                    (r.data.get('awarded') and any(w['key'] == filters['supplier'] for w in winners(r)))]
    history_rows.sort(key=lambda r: (r.published_on or date.min, r.pk), reverse=True)
    start = (filters['page'] - 1) * PAGE_SIZE
    # Reuse the official-source serializer, but omit the unrelated similarity score.
    results = [{k: v for k, v in serialize(0, r).items() if k != 'similarity'} for r in history_rows[start:start + PAGE_SIZE]]
    return {**base, 'mode': 'data' if selected else 'empty', 'summary': summary, 'suppliers': ranking,
            'signals': signals, 'results': results, 'history_count': len(history_rows),
            'message': '' if selected else 'Za tega naročnika v izbranem obdobju in področju ni oddaj v zbrani zbirki.'}
