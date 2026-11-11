"""Evidence-backed, deterministic what-if suggestions. Never writes company facts."""
from copy import deepcopy
import hashlib
import json
import math
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import Tender, Notification, ImprovementPlan
from .seed import get_profile, today
from .documents import active_documents
from .matching import (serialize_tender, evaluate_requirement, text_normalize,
                       certification_key, certification_needs_review)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def company_key(profile=None):
    profile = profile or get_profile()
    number = ''.join(profile.get('registration_number', '').split()).casefold()
    if number.isdigit() and len(number) == 7:
        number += '000'
    return digest(number or [text_normalize(profile.get('name', '')), text_normalize(profile.get('address', ''))])


def action_key(action):
    canonical = dict(action)
    if action['kind'] == 'certification':
        canonical['certification'] = certification_key(action['certification'])
    elif action['kind'] == 'technology':
        canonical['technologies'] = sorted(text_normalize(t) for t in action['technologies'])
    return digest(canonical)


def clean_actions(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 20:
        raise ValidationError('Izberite od 1 do 20 izboljšav.')
    result = {}
    def number(value, maximum=1000000000000, nullable=False):
        if nullable and value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
            raise ValidationError('Neveljaven prag izboljšave.')
        return value
    for item in values:
        if not isinstance(item, dict):
            raise ValidationError('Neveljavna izboljšava.')
        kind = item.get('kind')
        action = {'kind': kind}
        if kind == 'certification':
            value = item.get('certification')
            if not isinstance(value, str) or not value.strip() or len(value) > 150:
                raise ValidationError('Vnesite naziv certifikata.')
            action['certification'] = value.strip()
            key = (kind, certification_key(value))
        elif kind == 'staff':
            target = number(item.get('minimum'), 10000)
            if target != int(target) or target < 1:
                raise ValidationError('Število sodelavcev mora biti pozitivno celo število.')
            action['minimum'] = max(int(target), result.get((kind,), {}).get('minimum', 0))
            key = (kind,)
        elif kind == 'technology':
            tech = item.get('technologies')
            if not isinstance(tech, list) or not 1 <= len(tech) <= 100 or not all(isinstance(t, str) and 0 < len(t.strip()) <= 150 for t in tech):
                raise ValidationError('Neveljaven seznam tehnologij.')
            previous = result.get((kind,), {}).get('technologies', [])
            unique = {text_normalize(t.strip()): t.strip() for t in previous + tech}
            action['technologies'] = [unique[k] for k in sorted(unique)]
            key = (kind,)
        elif kind == 'reference':
            domain = item.get('domain', '')
            if not isinstance(domain, str) or not domain.strip() or len(domain) > 150:
                raise ValidationError('Referenca potrebuje konkretno področje.')
            domain = text_normalize(domain.strip())
            count = number(item.get('minimum_count', 1), 100)
            age = number(item.get('max_age_years'), 100, nullable=True)
            value = number(item.get('minimum_value'), nullable=True)
            if count < 1 or count != int(count) or (age is not None and (age < 1 or age != int(age))):
                raise ValidationError('Neveljavno število ali starost referenc.')
            previous = result.get((kind, domain), {})
            ages = [x for x in [age, previous.get('max_age_years')] if x is not None]
            vals = [x for x in [value, previous.get('minimum_value')] if x is not None]
            action.update(domain=domain, minimum_count=max(int(count), previous.get('minimum_count', 1)),
                          minimum_value=max(vals) if vals else None, max_age_years=min(ages) if ages else None)
            key = (kind, domain)
        elif kind == 'complete_profile':
            field = item.get('field')
            domain = item.get('domain', '')
            if field not in ('references', 'staff_count', 'technologies', 'certifications') or not isinstance(domain, str) or len(domain) > 150:
                raise ValidationError('Neveljavno polje za dopolnitev.')
            action.update(field=field, domain=text_normalize(domain.strip()))
            key = (kind, field, action['domain'])
        else:
            raise ValidationError('Nepodprta izboljšava.')
        result[key] = action
    return sorted(result.values(), key=lambda x: json.dumps(x, sort_keys=True))


def action_label(action):
    kind = action['kind']
    domain = {'sport': 'šport', 'energy': 'energetsko spremljanje', 'satellite': 'analiza satelitskih posnetkov'}.get(action.get('domain'), action.get('domain', ''))
    if kind == 'certification':
        return 'Pridobitev ' + action['certification']
    if kind == 'staff':
        return f"Ekipa z najmanj {action['minimum']} sodelavci"
    if kind == 'technology':
        return 'Znanje tehnologij: ' + ', '.join(action['technologies'])
    if kind == 'reference':
        label = f"Primerljive reference ({domain}): najmanj {action['minimum_count']}"
        if action['minimum_value'] is not None:
            label += f"; ena v vrednosti vsaj {action['minimum_value']:,.0f} EUR".replace(',', '.')
        if action['max_age_years']:
            label += f"; v zadnjih {action['max_age_years']} letih"
        return label
    names = {'references': 'podatke o referencah', 'staff_count': 'podatek o velikosti ekipe',
             'technologies': 'seznam tehnologij', 'certifications': 'podatke o certifikatih'}
    return 'Dopolnite ' + names[action['field']] + (f" ({domain})" if domain else '')


def reference_matches(ref, action):
    year = ref.get('year')
    return (text_normalize(ref.get('domain', '')) == action['domain'] and ref.get('confirmed') is True
            and (not action['max_age_years'] or (year is not None and today().year - action['max_age_years'] < year <= today().year)))


def simulate(profile, actions):
    hypothetical = deepcopy(profile)
    for action in actions:
        kind = action['kind']
        if kind == 'certification':
            if certification_key(action['certification']) not in {certification_key(c) for c in hypothetical.get('certifications', [])}:
                hypothetical.setdefault('certifications', []).append(action['certification'])
        elif kind == 'technology':
            tech = hypothetical.setdefault('technologies', [])
            known = {text_normalize(t) for t in tech}
            tech.extend(t for t in action['technologies'] if text_normalize(t) not in known)
        elif kind == 'staff':
            hypothetical['staff_count'] = max(hypothetical.get('staff_count') or 0, action['minimum'])
        elif kind == 'reference':
            refs = hypothetical.setdefault('references', [])
            valid = [r for r in refs if reference_matches(r, action)]
            count = max(0, action['minimum_count'] - len(valid))
            value = action['minimum_value']
            if value is not None and not any(r.get('value') is not None and r['value'] >= value for r in valid):
                count = max(count, 1)
            for index in range(count):
                refs.append({'id': f"simulation-{digest(action)[:12]}-{index}", 'title': 'Predpostavljena zaključena referenca',
                             'description': 'Samo predpostavka razvojnega načrta.', 'domain': action['domain'],
                             'value': value, 'year': today().year, 'confirmed': True})
    return hypothetical


def snapshot(profile=None):
    profile = profile or get_profile()
    records = []
    for tender in Tender.objects.all():
        docs = active_documents(tender)
        before = serialize_tender(tender, profile, docs)
        if before['status'] in ('open', 'closed') and before['match']['level'] != 'low':
            records.append((tender, docs, before))
    return profile, records


def completion_applies(action, requirement):
    field = action.get('field')
    kind = requirement.get('kind')
    if field == 'references':
        return kind in ('reference_count', 'reference_value') and (not action['domain'] or text_normalize(requirement.get('domain') or '') == action['domain'])
    return {'staff_count': 'staff', 'technologies': 'technology', 'certifications': 'certification'}.get(field) == kind


def evaluate(actions, source_type, context=None):
    actions = clean_actions(actions)
    if source_type not in ('demo', 'real'):
        raise ValidationError('Izberite demo ali resnične razpise.')
    profile, records = context or snapshot()
    hypothetical = simulate(profile, actions)
    groups = {'open': [], 'historical': []}
    completion = [a for a in actions if a['kind'] == 'complete_profile']
    for tender, docs, before in records:
        if before['source_type'] != source_type:
            continue
        after = serialize_tender(tender, hypothetical, docs)
        requirements = {(d.id, r['id']): r for d in docs for r in d.extraction.get('requirements', [])}
        previous = {(c['document_id'], c['id']): c for c in before['match']['conditions']}
        changes, unresolved = [], []
        for condition in after['match']['conditions']:
            key = (condition['document_id'], condition['id'])
            old = previous[key]
            improved = old['status'] != 'met' and condition['status'] == 'met'
            missing = old['status'] == 'unknown' and any(completion_applies(a, requirements.get(key, {})) for a in completion)
            if improved or missing:
                changes.append({'before': old, 'after': condition, 'improved': improved})
            if condition['status'] != 'met':
                unresolved.append(condition)
        if not changes:
            continue
        group = 'open' if before['status'] == 'open' else 'historical'
        groups[group].append({'id': tender.pk, 'title': before['title'], 'deadline': before['deadline'],
                              'source_type': source_type, 'status': before['status'],
                              'before_recommendation': before['match']['recommendation'],
                              'after_recommendation': after['match']['recommendation'],
                              'newly_recommended': group == 'open' and before['match']['recommendation'] != 'recommended' and after['match']['recommendation'] == 'recommended',
                              'changes': changes, 'remaining_conditions': unresolved,
                              'open_question': after['match']['open_question'],
                              'documentation_incomplete': not docs or any(d.status != 'processed' or d.extraction.get('mode') == 'unprocessed' or d.extraction.get('rejected_requirements', 0) for d in docs)})
    summary = {}
    for group, rows in groups.items():
        summary[group] = {'affected_tenders': sum(any(c['improved'] for c in r['changes']) for r in rows),
                          'newly_recommended': sum(r['newly_recommended'] for r in rows),
                          'improved_conditions': sum(c['improved'] for r in rows for c in r['changes']),
                          'needs_data': sum(any(c['status'] == 'unknown' for c in r['remaining_conditions']) for r in rows)}
    return {'actions': actions, 'labels': [action_label(a) for a in actions], 'source_type': source_type,
            'summary': summary, **groups, 'evaluated_at': timezone.now().isoformat(),
            'assumptions': ['Učinek je izračunan na začasni kopiji današnjega profila. Dejanski profil ostane nespremenjen.',
                            'Predpostavljene reference so zaključene in potrjene letos; predpostavljene kompetence so že pridobljene. Čas pridobitve ni ocenjen.',
                            'Pretekli razpisi prikazujejo primerjavo današnjega profila s shranjenimi pogoji, ne prihodnjih priložnosti.']}


def candidates(profile, records):
    found = {}
    for _, docs, before in records:
        for doc in docs:
            if doc.status != 'processed':
                continue
            for req in doc.extraction.get('requirements', []):
                condition = evaluate_requirement(req, profile)
                if condition['status'] == 'met':
                    continue
                kind = req.get('kind')
                action = None
                if kind == 'certification':
                    if not certification_needs_review(req):
                        action = {'kind': kind, 'certification': req['certification']}
                    else:
                        action = {'kind': 'complete_profile', 'field': 'certifications'}
                elif kind == 'staff':
                    action = {'kind': kind, 'minimum': req.get('minimum')} if profile.get('staff_count') is not None else {'kind': 'complete_profile', 'field': 'staff_count'}
                elif kind == 'technology':
                    action = {'kind': kind, 'technologies': req.get('technologies')} if profile.get('technologies') else {'kind': 'complete_profile', 'field': 'technologies'}
                elif kind in ('reference_count', 'reference_value'):
                    domain = req.get('domain') or ''
                    if condition['status'] == 'unknown' or not domain:
                        action = {'kind': 'complete_profile', 'field': 'references', 'domain': domain}
                    else:
                        action = {'kind': 'reference', 'domain': domain, 'minimum_count': req['minimum'] if kind == 'reference_count' else 1,
                                  'minimum_value': req['minimum'] if kind == 'reference_value' else None, 'max_age_years': req.get('max_age_years')}
                if action:
                    try:
                        action = clean_actions([action])[0]
                    except ValidationError:
                        continue
                    found[(before['source_type'], action_key(action))] = action
    return [(source, action) for (source, _), action in sorted(found.items())]


def title_and_body(result):
    label = ' + '.join(result['labels'])
    current, history = result['summary']['open'], result['summary']['historical']
    if current['affected_tenders']:
        count = current['affected_tenders']
        noun = 'odprtem razpisu' if count == 1 else 'odprtih razpisih'
        body = f"Dodaten pogoj bi izpolnili pri {count} {noun}. Novo priporočeni za pregled: {current['newly_recommended']}."
    elif current['needs_data']:
        count = current['needs_data']
        noun = 'odprtem razpisu' if count == 1 else 'odprtih razpisih'
        body = f"Pri {count} {noun} manjka podatek za presojo. Dopolnite profil; pridobitev novih zmogljivosti morda ni potrebna."
    else:
        body = f"Učinek pri preteklih razpisih: {history['affected_tenders']}; potrebna dopolnitev podatkov: {history['needs_data']}. To niso odprte priložnosti."
    return label[:250], body


def opportunity_ids(result):
    return {r['id'] for r in result.get('open', []) if any(c['improved'] for c in r['changes'])}, {r['id'] for r in result.get('open', []) if r['newly_recommended']}


@transaction.atomic
def refresh_suggestions():
    profile, records = context = snapshot()
    identity = company_key(profile)
    plans = list(ImprovementPlan.objects.filter(company_key=identity))
    saved = {(p.source_type, action_key(action)) for p in plans for action in p.actions}
    scored = []
    for source, action in candidates(profile, records):
        result = evaluate([action], source, context)
        if not result['open'] and not result['historical']:
            continue
        current = result['summary']['open']
        rank = (source == 'real' and bool(result['open']), bool(result['open']), current['newly_recommended'], current['improved_conditions'], current['affected_tenders'], len(result['historical']))
        scored.append((rank, action_key(action), source, result))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    unsaved = 0
    visible = []
    for _, action_hash, source, result in scored:
        if (source, action_hash) not in saved:
            if unsaved >= 5:
                continue
            unsaved += 1
        key = f'improvement:{identity}:{source}:{action_hash}'
        title, body = title_and_body(result)
        item, created = Notification.objects.get_or_create(event_key=key, defaults={
            'company_key': identity, 'type': 'improvement', 'title': title, 'body': body,
            'is_demo': source == 'demo', 'payload': result})
        old_open, old_recommended = opportunity_ids(item.payload)
        new_open, new_recommended = opportunity_ids(result)
        if not created and (new_open - old_open or new_recommended - old_recommended):
            item.read = False
        # Stable evaluations do not write SQLite on every browser poll.
        comparable = {k: v for k, v in result.items() if k != 'evaluated_at'}
        old = {k: v for k, v in item.payload.items() if k != 'evaluated_at'}
        if not created and (comparable != old or not item.active or item.title != title or item.body != body):
            item.title, item.body, item.payload, item.active = title, body, result, True
            item.save(update_fields=['title', 'body', 'payload', 'active', 'read'])
        visible.append(item.pk)
    Notification.objects.filter(type='improvement', company_key=identity, active=True).exclude(pk__in=visible).update(active=False, read=True)


def visible_notifications():
    return Notification.objects.filter(Q(type='improvement', company_key=company_key(), active=True) | ~Q(type='improvement'))


def serialize_plan(plan, context=None):
    return {'id': plan.pk, 'name': plan.name, 'actions': plan.actions, 'source_type': plan.source_type,
            'created_at': plan.created_at.isoformat(), 'updated_at': plan.updated_at.isoformat(),
            'evaluation': evaluate(plan.actions, plan.source_type, context)}
