"""Participants from explicitly sourced opening/award records, scoped to one awarded lot."""
import re
from urllib.parse import urlsplit
from django.db import transaction
from .models import PastAward

LABELS = {'winner': 'Zmagovalec', 'not_selected': 'Ni bil izbran', 'unknown': 'Prijavljen – izid ni potrjen'}


def participants(award):
    url = f'https://www.enarocanje.si/#/pregled-objav/{award.notice_id}'
    result = [{**w, 'outcome': 'winner', 'label': LABELS['winner'], 'source_url': url,
               'provenance': 'award_notice'} for w in award.data.get('winners', [])]
    # Match registration identifiers exactly. Similar names cannot establish a result.
    winner_ids = {w['registration_number'] for w in result if w.get('registration_number')}
    for entry in award.data.get('participants', []):
        if entry.get('registration_number') in winner_ids:
            continue
        result.append({**entry, 'label': LABELS[entry['outcome']], 'provenance': 'imported_record'})
    return result


def import_participants(records):
    if not isinstance(records, list):
        raise ValueError('Pričakovan je seznam zapisov po sklopih.')
    prepared = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('participants'), list):
            raise ValueError('Vsak zapis potrebuje award_id in seznam participants.')
        award = PastAward.objects.get(pk=record.get('award_id'))
        entries = []
        for person in record['participants']:
            if not isinstance(person, dict):
                raise ValueError('Neveljaven zapis ponudnika.')
            name, reg = person.get('name'), person.get('registration_number', '')
            outcome, source = person.get('outcome', 'unknown'), person.get('source_url', '')
            parsed = urlsplit(source)
            if (not isinstance(name, str) or not name.strip() or len(name) > 300 or
                not isinstance(reg, str) or (reg and not re.fullmatch(r'\d{7,10}', reg)) or
                outcome not in ('unknown', 'not_selected') or parsed.scheme != 'https' or
                parsed.hostname not in ('ejn.gov.si', 'www.enarocanje.si', 'enarocanje.si') or
                parsed.username or parsed.password or parsed.port not in (None, 443)):
                raise ValueError('Ponudnik potrebuje veljavno ime, izid in povezavo do javnega zapisnika. Zmagovalca določa obvestilo o oddaji.')
            entries.append({'name': name.strip(), 'registration_number': reg, 'outcome': outcome, 'source_url': source})
        prepared.append((award, entries))
    with transaction.atomic():
        for award, entries in prepared:
            merged = {(p.get('registration_number') or p['name'].casefold()): p for p in award.data.get('participants', [])}
            merged.update({(p['registration_number'] or p['name'].casefold()): p for p in entries})
            award.data = {**award.data, 'participants': list(merged.values())}
            award.save(update_fields=['data', 'imported_at'])
    return len(prepared)
