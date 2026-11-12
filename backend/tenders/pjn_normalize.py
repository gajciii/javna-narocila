"""Mapping verified against public PJN JSON and official codelists on 2026-11-10."""
import json
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from django.utils import timezone
from django.utils.html import strip_tags

from .pjn_transport import official_url, submission_url

SOURCE = 'Javne informacije Slovenije – portal javnih naročil'


@lru_cache(maxsize=1)
def codelists():
    return json.loads((Path(__file__).resolve().parent.parent / 'source_data/pjn-codelists.json').read_text(encoding='utf-8'))


def timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return timezone.make_aware(result) if timezone.is_naive(result) else result
    except ValueError:
        return None


def text(value, limit=10000):
    return strip_tags(value).strip()[:limit] if isinstance(value, str) else ''


def eur_value(obj):
    value = obj.get('vrednostOcenjenaBrezDDV')
    currency = codelists()['currencies'].get(str(obj.get('idSifValutaOcenjenaBrezDDV')), {}).get('koda')
    if currency != 'EUR' or isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        return None
    return value


def cpvs(obj, extra_key='obrazecCpv'):
    ids = [obj.get('idSifCpv')] + [x.get('idSifCpv', x.get('id')) for x in obj.get(extra_key, []) if isinstance(x, dict)]
    return list({v['code']: v for key in ids if (v := codelists()['cpv'].get(str(key)))}.values())


def normalize_notice(raw, notice_id):
    if not isinstance(raw, dict) or str(raw.get('id')) != str(notice_id):
        raise ValueError('ID v odzivu se ne ujema z zahtevano objavo.')
    title = text(raw.get('naslov'), 500)
    buyers = [text(n.get('naziv'), 300) for n in raw.get('narocnik', []) if isinstance(n, dict) and n.get('naziv')]
    if not title or not buyers or not isinstance(raw.get('idDosje'), int):
        raise ValueError('Objava nima prepoznanega naslova, naročnika ali dosjeja.')
    codes = codelists()
    kind = {'services': 'services', 'supplies': 'goods', 'works': 'works'}.get(codes['kinds'].get(str(raw.get('idSifNarociloVrsta')), {}).get('koda'))
    if kind is None:
        raise ValueError('Vrsta naročila ni prepoznana; izvorni odziv je shranjen.')
    phase = codes['phases'].get(str(raw.get('idSifPostopekFaza')), {})
    deadline = timestamp(raw.get('datumDoPonudba'))
    published = timestamp(raw.get('objavaDejanskaDatum'))
    # 'Objavljen' describes publication, not an open application period.
    status = 'unconfirmed'
    if phase.get('koda') == 'competition' and raw.get('idObrazecStatus') == 100 and deadline:
        status = 'open' if deadline > timezone.now() else 'closed'
    elif phase.get('koda') in ('result', 'cont-modif'):
        status = 'closed'
    if str(notice_id) == '1144799':
        status = 'cancelled'  # Independently verified official e-JN archive.
    locations = [codes['nuts'].get(str(x.get('idSifNuts')), {}).get('naziv') for x in raw.get('obrazecKraj', []) if isinstance(x, dict)]
    classifications = cpvs(raw)
    summary = text(raw.get('kratekOpis')) or title
    lots, criteria = [], []
    for index, lot in enumerate(raw.get('obrazecSklop', [])):
        if not isinstance(lot, dict):
            continue
        lot_codes = cpvs(lot, 'obrazecSklopCpv')
        if raw.get('sklopiDelitev'):
            lots.append({'id': str(lot.get('id', index)), 'title': text(lot.get('naslov'), 500),
                         'summary': text(lot.get('opis')), 'topics': [x['label'] for x in lot_codes],
                         'kind': {'services': 'services', 'supplies': 'goods', 'works': 'works'}.get(codes['kinds'].get(str(lot.get('idSifNarociloVrsta')), {}).get('koda'), kind)})
        for item in lot.get('obrazecSklopMerilo', []):
            # PJN has different number semantics (weight, threshold, fixed value).
            # Keep the text, but never label an unknown number as a percentage.
            label = text(item.get('naziv') or item.get('opis'), 500)
            if label:
                criteria.append({'title': label, 'weight': None})
    attachment = raw.get('razpisnaDokumentacijaURL')
    attachment = attachment if isinstance(attachment, str) and official_url(attachment, attachment=True) else None
    correction = bool(raw.get('idObrazecPrejPopravek'))
    return {
        'id': 'ijs-archive' if str(notice_id) == '1144799' else f"pjn-dosje-{raw['idDosje']}",
        'title': title, 'buyer': '; '.join(buyers), 'region': ', '.join(dict.fromkeys(x for x in locations if x)) or 'Ni podatka',
        'kind': kind, 'cpv': [x['code'] for x in classifications], 'topics': [x['label'] for x in classifications],
        'value': eur_value(raw), 'published_at': published.date().isoformat() if published else None,
        'deadline': deadline.isoformat() if deadline else None, 'status': status,
        'source_type': 'real', 'source_url': f'https://www.enarocanje.si/#/pregled-objav/{notice_id}',
        'summary': summary, 'description': summary, 'technologies': [], 'is_new': False,
        'has_update': correction, 'version': 1, 'criteria': criteria, 'lots': lots, 'changes': [],
        'source_metadata': {'buyers': [{'name': text(n.get('naziv'), 300),
            'registration_number': n.get('maticna') if isinstance(n.get('maticna'), str) else ''}
            for n in raw.get('narocnik', []) if isinstance(n, dict) and n.get('naziv')],
            'notice_id': str(notice_id), 'dossier_id': raw['idDosje'], 'notice_number': raw.get('objavaIdent'),
            'attribution': SOURCE, 'fetched_at': timezone.now().isoformat(), 'published_timestamp': published.isoformat() if published else None,
            'phase': phase.get('naziv', 'Ni podatka'), 'previous_notice_id': raw.get('idObrazecPrejPopravek'),
            'correction_description': text(raw.get('popravekOpis')), 'attachment_url': attachment, 'submission_url': submission_url(raw.get('elektronskaPredlozitevURL')),
            'external_documentation_url': raw.get('razpisnaDokumentacijaURL') if isinstance(raw.get('razpisnaDokumentacijaURL'), str) else None,
            'access_restricted': raw.get('dokumentacijaDostopOmejen') is True,
            'attachments_processed': False, 'codelists_as_of': codes['retrieved_at']},
    }
