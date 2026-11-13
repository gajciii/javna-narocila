"""Public contract awards won by the company, offered as profile references."""
import re

from .models import PastAward

EVIDENCE_SOURCE = 'Obvestilo o oddaji naročila, Portal javnih naročil'
DOMAINS = (('45', 'construction'), ('72', 'software'), ('48', 'software'))


def identity(value):
    compact = re.sub(r'\s+', '', value or '')
    return f'{compact}000' if re.fullmatch(r'\d{7}', compact) else compact


def domain(cpv):
    for code in cpv or []:
        for prefix, name in DOMAINS:
            if code.startswith(prefix):
                return name
    return 'other'


def reference(award):
    data = award.data
    title = data.get('title') or 'Javno naročilo'
    if data.get('lot_title'):
        title = f"{title} – {data['lot_title']}"
    euro = data.get('currency') in (None, 'EUR')
    description = ' '.join(part for part in (
        f"Naročnik: {data.get('buyer')}." if data.get('buyer') else '',
        data.get('description') or '',
        'Leto je leto oddaje naročila; preverite leto zaključka del.') if part)
    lot = award.pk.rsplit('-', 1)[-1]
    return {
        'id': f'award-{award.pk}'[:100], 'title': title[:300], 'description': description[:2000],
        'domain': domain(data.get('cpv')), 'value': data.get('awarded_value') if euro else None,
        'year': award.published_on.year if award.published_on else None,
        # Official award notice is the evidence, so the reference counts without manual confirmation.
        'confirmed': True,
        'project_identifier': f"{data.get('notice_number') or award.notice_id}/{lot}",
        'evidence_source': EVIDENCE_SOURCE,
        'evidence_url': f'https://www.enarocanje.si/#/pregled-objav/{award.notice_id}',
    }


def company_awards(profile):
    reg = identity(profile.get('registration_number'))
    if not re.fullmatch(r'\d{10}', reg):
        return {'registration_number': reg, 'items': [],
                'message': 'Za iskanje zmag vnesite matično številko podjetja in shranite profil.'}
    existing = {r.get('id') for r in profile.get('references', [])} | {
        r.get('project_identifier') for r in profile.get('references', []) if r.get('project_identifier')}
    # Text prefilter works on SQLite and PostgreSQL; the exact identifier check decides.
    awards = PastAward.objects.filter(data__winners__icontains=reg, data__awarded=True).order_by('-published_on', 'pk')
    items = []
    for award in awards:
        if not any(identity(w.get('registration_number')) == reg for w in award.data.get('winners', [])):
            continue
        ref = reference(award)
        items.append({'reference': ref, 'buyer': award.data.get('buyer', ''), 'published_on': award.published_on.isoformat() if award.published_on else None,
                      'joint': len(award.data.get('winners', [])) > 1,
                      'added': ref['id'] in existing or ref['project_identifier'] in existing})
    oldest = PastAward.objects.order_by('published_on').values_list('published_on', flat=True).first()
    return {'registration_number': reg, 'items': items, 'covered_from': oldest.isoformat() if oldest else None}
