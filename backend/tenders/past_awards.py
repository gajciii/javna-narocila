"""Similar past awards for a tender: who won, how many bids, at what price.

Source data are published PJN award notices (phase "Rezultat"). ``from_pjn`` maps the public PJN
``obrazecGet`` JSON to the record shape of the ``publicmoney/enarocanje-slovenia-scraper`` Apify actor,
which ``normalize_notice`` reads; downloading lives in ``pjn_sync`` (``record_awards``, ``sync_awards``).
The initial table ships in ``source_data/past_awards/`` and loads automatically into an empty table;
the raw scraper exports are kept next to it for re-import. Retrieval is deterministic text + CPV similarity; when a Gemini key
is configured, the Gemini Decisions API re-ranks the candidates. Every result links to its official
notice. Records are untrusted data: only bounded, typed fields are kept.
"""
import functools
import gzip
import hashlib
import json
import logging
import math
import os
import re
import statistics
from collections import Counter
from datetime import date
from pathlib import Path

import requests
from django.db import transaction
from django.db.models import Max, Min

from .embeddings import award_invalidation
from .models import PastAward, SimilarAwardsCache

log = logging.getLogger(__name__)

GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/decisions'
KINDS = {'SERVICES': 'services', 'SUPPLIES': 'goods', 'WORKS': 'works'}
SOURCE = {'label': 'Portal javnih naročil (obvestila o oddaji)', 'license': 'CC BY 4.0',
          'attribution': 'Ministrstvo za javno upravo, Portal javnih naročil'}
CANDIDATES = 40      # sent to Gemini for re-ranking
RESULTS = 8
PER_NOTICE = 2       # a 40-lot notice must not fill the whole list
AI_THRESHOLD = 0.5   # P(similar) from Gemini
TEXT_THRESHOLD = 0.3
VECTOR_THRESHOLD = 0.5  # cosine similarity shown without AI re-ranking
VECTOR_POOL = 200       # nearest awards read from the HNSW index before filtering
EF_SEARCH = 400         # pgvector default (40) misses clear matches; 400 matched exact search in tests
FUSION_K = 60           # reciprocal rank fusion constant
STOPWORDS = {
    'naročilo', 'naročila', 'javno', 'javnega', 'izvedba', 'izvedbo', 'dobava', 'dobavo', 'storitve', 'storitev',
    'predmet', 'sklop', 'sklopa', 'skladu', 'zahtevami', 'dokumentacije', 'dokumentacijo', 'naročnika', 'naročnik',
    'ponudbe', 'pogodbe', 'pogodba', 'okvirni', 'okvirnega', 'sporazum', 'sporazuma', 'obdobje', 'leto', 'leta',
    'let', 'vključno', 'potrebe', 'potrebno', 'oziroma', 'katerih', 'ki', 'ter', 'tudi', 'za', 'pri', 'del',
    'dela', 'specifikacijo', 'specifikacijami', 'tehnično', 'tehnične', 'tehnični', 'razpisne', 'razpisno',
    'mala', 'male', 'vrednosti', 'vrednost', 'skupaj', 'nabava', 'nakup', 'izbor', 'izvajalca', 'izvajalec',
}
_index = {'revision': None}
BUNDLE = Path(__file__).resolve().parent.parent / 'source_data' / 'past_awards' / 'past_awards.json.gz'


def clean(value, limit=600):
    return re.sub(r'\s+', ' ', value).strip()[:limit] if isinstance(value, str) else ''


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def count(value):
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10000 else None


def cpv_code(value):
    match = re.match(r'\s*(\d{8})', value) if isinstance(value, str) else None
    return match.group(1) if match else None


def registration(value):
    return value if isinstance(value, str) and re.fullmatch(r'\d{7,10}', value) else ''


def parse_date(value):
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None


def normalize_notice(raw):
    """One PJN award notice -> PastAward field dicts, one per awarded lot."""
    if not isinstance(raw, dict) or not isinstance(raw.get('id'), int):
        return []
    notice_id = str(raw['id'])
    lots = {lot.get('lotId'): lot for lot in raw.get('lots') or [] if isinstance(lot, dict)}
    notice_cpv = cpv_code(raw.get('mainCpv'))
    framework = raw.get('frameworkAgreement') is True
    out = []
    for award in raw.get('awards') or []:
        if not isinstance(award, dict):
            continue
        lot = lots.get(award.get('lotId'), {})
        cpvs = [code for code in (cpv_code(c) for c in lot.get('cpv') or []) if code] or ([notice_cpv] if notice_cpv else [])
        currency = award.get('currency') or lot.get('currency') or raw.get('currency')
        winners = [{'name': clean(w.get('name'), 300), 'registration_number': registration(w.get('registrationNumber'))}
                   for w in award.get('winners') or [] if isinstance(w, dict) and clean(w.get('name'))]
        lot_title = clean(lot.get('title'), 300)
        title = clean(raw.get('title'), 300)
        out.append({
            'id': f"pjn-{notice_id}-{award.get('lotId') if isinstance(award.get('lotId'), int) else len(out)}",
            'notice_id': notice_id,
            'dossier_id': str(raw['dossierId']) if isinstance(raw.get('dossierId'), int) else '',
            'published_on': parse_date(raw.get('publicationDate')),
            'data': {
                'notice_number': clean(raw.get('noticeNumber'), 60),
                'previous_notice_id': str(raw['previousNoticeId']) if re.fullmatch(r'[1-9]\d{0,29}', str(raw.get('previousNoticeId') or '')) else '',
                'title': title, 'lot_title': lot_title if lot_title and lot_title != title else '',
                'description': clean(lot.get('description') or raw.get('shortDescription'), 1200),
                'buyer': clean(raw.get('buyer'), 300), 'buyer_registration_number': registration(raw.get('buyerRegistrationNumber')),
                'kind': KINDS.get(lot.get('contractType') or raw.get('contractType')),
                'cpv': cpvs[:5], 'procedure': clean(raw.get('procedureTypeName'), 120),
                'framework': framework or lot.get('frameworkAgreement') not in (None, 'none'),
                'currency': currency if isinstance(currency, str) and re.fullmatch(r'[A-Z]{3}', currency) else None,
                'estimated_value': number(lot.get('estimatedValue')),
                'awarded_value': number(award.get('awardedValue')),
                'lowest_offer': number(award.get('lowestAdmissibleOffer')),
                'highest_offer': number(award.get('highestAdmissibleOffer')),
                'tenders_received': count(award.get('tendersReceived')),
                'awarded': bool(winners) and award.get('status') == 'selec-w',
                'winners': winners,
            },
        })
    return out


# PJN ``idSifPostopekVrsta`` and ``idSifOddajaStatus``; verified 2026-11-12 against the same notices in the
# Apify export (procedureTypeName, awards[].status), which reads these codelists by name.
PROCEDURES = {
    1: 'Odprti postopek',
    2: 'Omejeni postopek / Postopek s predhodnim ugotavljanjem sposobnosti (ZJNPOV)',
    3: 'Konkurenčni postopek s pogajanji / Postopek s pogajanji z objavo / Postopek s pogajanji po predhodni objavi (ZJNPOV)',
    4: 'Konkurenčni dialog',
    6: 'Oddaja javnega naročila brez predhodne objave',
    7: 'Naročilo male vrednosti',
    8: 'Drugo',
    9: 'Postopek zbiranja ponudb po predhodni objavi',
}
AWARD_STATUS = {1: 'clos-nw', 2: 'selec-w'}
PJN_KINDS = {'services': 'SERVICES', 'supplies': 'SUPPLIES', 'works': 'WORKS'}


def from_pjn(raw):
    """Public PJN ``obrazecGet`` JSON of an award notice -> the record shape ``normalize_notice`` reads.

    Returns None for notices that are not in the result phase."""
    from .pjn_normalize import codelists, cpvs, text
    if not isinstance(raw, dict) or not isinstance(raw.get('id'), int):
        return None
    codes = codelists()
    if codes['phases'].get(str(raw.get('idSifPostopekFaza')), {}).get('koda') != 'result':
        return None

    def kind(obj):
        return PJN_KINDS.get(codes['kinds'].get(str(obj.get('idSifNarociloVrsta')), {}).get('koda'))

    def currency(code):
        return codes['currencies'].get(str(code), {}).get('koda')

    def framework(lot):
        agreement = lot.get('idSifSporazum')
        return None if agreement is None else 'none' if agreement == 1 else 'framework'

    def code(obj, extra_key):
        return [item['code'] for item in cpvs({'idSifCpv': obj.get('idSifCpv'), 'extra': obj.get(extra_key) or []}, 'extra')]

    buyer = next((b for b in raw.get('narocnik') or [] if isinstance(b, dict)), {})
    lots = [{'lotId': lot.get('id'), 'title': text(lot.get('naslov'), 500), 'description': text(lot.get('opis')),
             'contractType': kind(lot) or kind(raw), 'cpv': code(lot, 'obrazecSklopCpv'),
             'estimatedValue': lot.get('vrednostOcenjenaBrezDDV'), 'currency': currency(lot.get('idSifValutaOcenjenaBrezDDV')),
             'frameworkAgreement': framework(lot)}
            for lot in raw.get('obrazecSklop') or [] if isinstance(lot, dict)]
    awards = [{'lotId': award.get('idObrazecSklop'), 'status': AWARD_STATUS.get(award.get('idSifOddajaStatus')),
               'tendersReceived': award.get('steviloPonudbe'), 'awardedValue': award.get('vrednostIzbrana'),
               'lowestAdmissibleOffer': award.get('vrednostMinDopustna'), 'highestAdmissibleOffer': award.get('vrednostMaxDopustna'),
               'currency': currency(award.get('idSifValutaIzbrana')),
               'winners': [{'name': w.get('naziv'), 'registrationNumber': w.get('maticna')}
                           for w in award.get('obrazecOddajaSubjekt') or [] if isinstance(w, dict)]}
              for award in raw.get('obrazecOddaja') or [] if isinstance(award, dict)]
    main = code({'idSifCpv': raw.get('idSifCpv')}, 'none')
    published = raw.get('objavaDejanskaDatum')
    return {
        'id': raw['id'], 'dossierId': raw.get('idDosje'), 'noticeNumber': raw.get('objavaIdent'),
        'previousNoticeId': raw.get('idObrazecPrejPopravek'),
        'title': text(raw.get('naslov'), 500), 'shortDescription': text(raw.get('kratekOpis')),
        'buyer': text(buyer.get('naziv'), 300), 'buyerRegistrationNumber': buyer.get('maticna'),
        'publicationDate': published[:10] if isinstance(published, str) else None,
        'contractType': kind(raw), 'mainCpv': main[0] if main else None,
        'procedureTypeName': PROCEDURES.get(raw.get('idSifPostopekVrsta')),
        'frameworkAgreement': any(lot['frameworkAgreement'] not in (None, 'none') for lot in lots),
        'currency': currency(raw.get('idSifValutaOcenjenaBrezDDV')), 'lots': lots, 'awards': awards,
    }


def import_notices(records):
    rows = [row for raw in records for row in normalize_notice(raw)]
    existing = set(PastAward.objects.filter(pk__in=[r['id'] for r in rows]).values_list('pk', flat=True))
    with transaction.atomic():
        for row in rows:
            old = PastAward.objects.filter(pk=row['id']).first()
            if old and old.data.get('participants'):
                row['data']['participants'] = old.data['participants']
            defaults = {k: v for k, v in row.items() if k != 'id'}
            PastAward.objects.update_or_create(pk=row['id'], defaults={**defaults, **award_invalidation(old, row['data'])})
    _index['revision'] = None
    return {'notices': len({r['notice_id'] for r in rows}), 'lots': len(rows),
            'created': len({r['id'] for r in rows} - existing), 'updated': len(existing)}


def read_json(path):
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as handle:
        return json.load(handle)


def write_bundle(path=BUNDLE):
    """Snapshot of the normalized table, reproducible (sorted, gzip without timestamp)."""
    rows = [{'id': a.pk, 'notice_id': a.notice_id, 'dossier_id': a.dossier_id,
             'published_on': a.published_on.isoformat() if a.published_on else None, 'data': a.data}
            for a in PastAward.objects.order_by('pk')]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=9, mtime=0, filename='') as handle:
        handle.write(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    return len(rows)


def ensure_past_awards(path=BUNDLE):
    """Load the bundled snapshot into an empty table; never overwrites imported data."""
    if PastAward.objects.exists() or not Path(path).exists():
        return 0
    rows = read_json(path)
    PastAward.objects.bulk_create([PastAward(id=r['id'], notice_id=r['notice_id'], dossier_id=r.get('dossier_id') or '',
                                             published_on=parse_date(r.get('published_on')), data=r['data'])
                                   for r in rows], batch_size=500, ignore_conflicts=True)
    _index['revision'] = None
    return len(rows)


def stems(text):
    return [word[:6] for word in re.findall(r'[a-zčšžćđ0-9]+', text.lower()) if len(word) >= 4 and word not in STOPWORDS and not word.isdigit()]


def vector(title, description, idf):
    counts = Counter()
    for word in stems(title):
        counts[word] += 2
    for word in stems(description):
        counts[word] += 1
    vec = {w: c * idf.get(w, idf.get(None, 1.0)) for w, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {w: v / norm for w, v in vec.items()}


def dataset_info():
    stats = PastAward.objects.aggregate(first=Min('published_on'), last=Max('published_on'), imported=Max('imported_at'))
    total = PastAward.objects.count()
    return {**SOURCE, 'lots': total, 'coverage_from': stats['first'].isoformat() if stats['first'] else None,
            'coverage_to': stats['last'].isoformat() if stats['last'] else None,
            'imported_at': stats['imported'].isoformat() if stats['imported'] else None}


def index():
    info = dataset_info()
    revision = (info['lots'], info['imported_at'])
    if _index['revision'] != revision:
        awards = list(PastAward.objects.all())
        docs = [stems(f"{a.data.get('title', '')} {a.data.get('lot_title', '')} {a.data.get('description', '')}") for a in awards]
        df = Counter(word for doc in docs for word in set(doc))
        idf = {w: math.log((1 + len(docs)) / (1 + n)) + 1 for w, n in df.items()}
        idf[None] = math.log(1 + len(docs)) + 1
        _index.update(revision=revision, info=info, idf=idf, awards=[
            (a, vector(f"{a.data.get('title', '')} {a.data.get('lot_title', '')}", a.data.get('description', ''), idf)) for a in awards])
    return _index


def cpv_bonus(codes, other):
    best = 0
    for a in codes:
        for b in other:
            shared = next((n for n in (8, 5, 4, 3, 2) if a[:n] == b[:n]), 0)
            best = max(best, shared)
    return {8: 0.25, 5: 0.18, 4: 0.14, 3: 0.1, 2: 0.05}.get(best, 0.0)


def query_text(data):
    lots = ' '.join(f"{lot.get('title', '')}" for lot in data.get('lots') or [])
    return f"{data.get('title', '')} {lots}", (data.get('description') or data.get('summary') or '')[:1500]


def procedure_number(notice_number):
    """'JN006195/2026-EUe29/01' -> 'JN006195/2026': all notices of one e-JN procedure share it."""
    match = re.match(r'(JN\d+/\d{4})', notice_number) if isinstance(notice_number, str) else None
    return match.group(1) if match else None


def candidates(data, idx, limit=CANDIDATES):
    title, description = query_text(data)
    query = vector(title, description, idx['idf'])
    own_dossier = str((data.get('source_metadata') or {}).get('dossier_id') or '')
    codes = [c for c in data.get('cpv') or [] if isinstance(c, str)]
    own_procedure = procedure_number((data.get('source_metadata') or {}).get('notice_number'))
    scored = []
    for award, vec in idx['awards']:
        if (own_dossier and award.dossier_id == own_dossier) or (own_procedure and procedure_number(award.data.get('notice_number')) == own_procedure):
            continue  # the tender's own procedure is not a "past similar" award
        text_score = sum(v * vec.get(w, 0.0) for w, v in query.items())
        bonus = cpv_bonus(codes, award.data.get('cpv') or [])
        if text_score < 0.08 and bonus < 0.18:
            continue
        kind = 0.03 if data.get('kind') and award.data.get('kind') == data.get('kind') else 0.0
        scored.append((min(1.0, 0.75 * text_score + bonus + kind), award))
    scored.sort(key=lambda item: (-item[0], -(item[1].published_on or date.min).toordinal()))
    return diverse(scored, limit)


def subject_text(data):
    """Subject of the tender without the buyer, so the buyer's unrelated purchases do not rank high."""
    title, description = query_text(data)
    return '\n'.join(part for part in (title.strip(), description.strip(), ', '.join(data.get('cpv') or [])) if part)


@functools.lru_cache(maxsize=512)
def query_vector(text):
    from .embeddings import embed
    return tuple(embed([text])[0])


def vector_candidates(data):
    """Nearest awards by meaning; [] when vectors are unavailable so the text match is used alone."""
    from django.db import connection, transaction
    from pgvector.django import CosineDistance
    from .embeddings import enabled
    text = subject_text(data)
    if not text or not enabled() or not PastAward.objects.filter(embedding__isnull=False).exists():
        return []
    vector = list(query_vector(text))
    own_dossier = str((data.get('source_metadata') or {}).get('dossier_id') or '')
    own_procedure = procedure_number((data.get('source_metadata') or {}).get('notice_number'))
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET LOCAL hnsw.ef_search = %s', [EF_SEARCH])
        rows = list(PastAward.objects.annotate(distance=CosineDistance('embedding', vector))
                    .order_by('distance')[:VECTOR_POOL])
    found = []
    for award in rows:
        if (own_dossier and award.dossier_id == own_dossier) or (own_procedure and procedure_number(award.data.get('notice_number')) == own_procedure):
            continue
        found.append((1 - award.distance, award))
    return found


def fused_candidates(data, idx, semantic):
    """Reciprocal rank fusion of meaning and word matches; CPV agreement breaks near ties."""
    text = candidates(data, idx, limit=VECTOR_POOL)
    if not semantic:
        return diverse(text, CANDIDATES), {}
    codes = [c for c in data.get('cpv') or [] if isinstance(c, str)]
    scores, awards, similarity = Counter(), {}, {}
    for rank, (score, award) in enumerate(semantic):
        scores[award.pk] += 1 / (FUSION_K + rank)
        awards[award.pk], similarity[award.pk] = award, score
    for rank, (score, award) in enumerate(text):
        scores[award.pk] += 1 / (FUSION_K + rank)
        awards.setdefault(award.pk, award)
    for pk, award in awards.items():
        scores[pk] += cpv_bonus(codes, award.data.get('cpv') or []) / FUSION_K
    ordered = sorted(awards.values(), key=lambda a: (-scores[a.pk], -(a.published_on or date.min).toordinal()))
    text_score = {award.pk: score for score, award in text}
    # Shown score: semantic similarity when known, otherwise the word-match score.
    return diverse([(similarity.get(a.pk, text_score.get(a.pk, 0.0)), a) for a in ordered], CANDIDATES), similarity


def diverse(scored, limit):
    per_notice, seen, out = Counter(), set(), []
    for score, award in scored:
        same = (award.notice_id, award.data.get('lot_title'))  # repeated lots of one notice add nothing
        if per_notice[award.notice_id] >= PER_NOTICE or same in seen:
            continue
        seen.add(same)
        per_notice[award.notice_id] += 1
        out.append((score, award))
        if len(out) == limit:
            break
    return out


def award_text(award):
    d = award.data
    return (f"Naslov: {d.get('title', '')}{' – ' + d['lot_title'] if d.get('lot_title') else ''}\nNaročnik: {d.get('buyer', '')}\n"
            f"CPV: {', '.join(d.get('cpv') or [])}\nOpis: {d.get('description', '')[:500]}")


def gemini_rank(data, found, api_key, model):
    title, description = query_text(data)
    body = {'model': model if model.startswith('models/') else f'models/{model}',
            'input': f"NOVI RAZPIS:\nNaslov: {title}\nNaročnik: {data.get('buyer', '')}\nCPV: {', '.join(data.get('cpv') or [])}\nOpis: {description[:800]}",
            'questions': {f'q{i}': {'type': 'noul', 'instructions': (
                'Ali je predmet spodnjega preteklega naročila iste vrste kot predmet NOVEGA RAZPISA (isto blago, ista storitev '
                'ali ista vrsta gradenj), tako da sta njegova konkurenca in cena uporabna primerjava? Naročnik, obseg, '
                'količina in trajanje se lahko razlikujejo. Le sorodno področje ali širša skupina CPV ne zadošča.\n\n') + award_text(award)}
                for i, (_, award) in enumerate(found)}}
    response = requests.post(GEMINI_URL, json=body, timeout=(5, 60), headers={'x-goog-api-key': api_key, 'Content-Type': 'application/json'})
    if response.status_code != 200:
        raise RuntimeError(f'Gemini Decisions API je vrnil status {response.status_code}.')
    ranked = []
    for qid, answer in (response.json().get('answers') or {}).items():
        position = int(qid[1:]) if qid[:1] == 'q' and qid[1:].isdigit() else -1
        probability = answer.get('noul') if isinstance(answer, dict) else None
        if 0 <= position < len(found) and isinstance(probability, (int, float)) and probability >= AI_THRESHOLD:
            ranked.append((float(probability), found[position][1]))
    ranked.sort(key=lambda item: (-item[0], -(item[1].published_on or date.min).toordinal()))
    return ranked


def serialize(score, award):
    from .participants import participants
    d = award.data
    return {'id': award.pk, 'notice_id': award.notice_id, 'participants': participants(award),
            'participant_coverage': 'partial_records' if d.get('participants') else 'winners_only',
            'notice_url': f'https://www.enarocanje.si/#/pregled-objav/{award.notice_id}',
            'published_on': award.published_on.isoformat() if award.published_on else None, 'similarity': round(score, 2),
            **{k: d.get(k) for k in ('notice_number', 'title', 'lot_title', 'buyer', 'kind', 'cpv', 'procedure', 'framework', 'currency',
                                     'estimated_value', 'awarded_value', 'lowest_offer', 'highest_offer', 'tenders_received', 'awarded', 'winners')}}


def median(values):
    return round(statistics.median(values), 2) if values else None


def summarize(results):
    awarded = [r for r in results if r['awarded']]
    bids = [r['tenders_received'] for r in results if r['tenders_received'] is not None]
    eur = [r for r in awarded if r['currency'] in (None, 'EUR')]
    ratios = [r['awarded_value'] / r['estimated_value'] for r in eur
              if not r['framework'] and r['awarded_value'] and r['estimated_value']]
    spreads = [r['highest_offer'] / r['lowest_offer'] - 1 for r in eur
               if r['lowest_offer'] and r['highest_offer'] and (r['tenders_received'] or 0) >= 2]
    winners = Counter()
    names = {}
    for r in awarded:
        for w in r['winners']:
            key = w['registration_number'] or w['name'].lower()
            winners[key] += 1
            names.setdefault(key, w)
    return {'count': len(results), 'awarded': len(awarded), 'not_awarded': len(results) - len(awarded),
            'median_tenders': median(bids), 'single_bid_share': round(sum(1 for b in bids if b == 1) / len(bids), 2) if bids else None,
            'median_price_to_estimate': median(ratios), 'price_to_estimate_count': len(ratios),
            'median_offer_spread': median(spreads), 'offer_spread_count': len(spreads),
            'top_winners': [{**names[k], 'wins': n} for k, n in winners.most_common(5)]}


def gemini_settings():
    return os.environ.get('GEMINI_API_KEY') or None, os.environ.get('GEMINI_DECISION_MODEL') or 'gemini-decision-1'


def similar_awards(tender):
    data = tender.data
    idx = index()
    base = {'tender_id': tender.pk, 'dataset': idx['info'], 'results': [], 'summary': summarize([]), 'warning': None}
    if data.get('source_type') != 'real':
        return {**base, 'mode': 'empty', 'message': 'Pretekle oddaje primerjamo samo z resničnimi objavami. Ta razpis je demo primer.'}
    if not idx['awards']:
        return {**base, 'mode': 'empty', 'message': 'Zbirka preteklih oddaj je prazna. Uvozite jo z ukazom import_past_awards.'}
    try:
        semantic = vector_candidates(data)
    except Exception as exc:  # The provider or index being unavailable must not hide word matches.
        log.warning('Vector candidates unavailable: %s', type(exc).__name__)
        semantic = []
    found, similarity = fused_candidates(data, idx, semantic)
    api_key, model = gemini_settings()
    mode, warning = 'text', None
    if api_key and found:
        key = hashlib.sha256(repr((query_text(data), data.get('cpv'), idx['revision'], model, [a.pk for _, a in found])).encode()).hexdigest()
        cached = SimilarAwardsCache.objects.filter(tender=tender, key=key).first()
        try:
            if cached:
                by_id = {a.pk: a for _, a in found}
                ranked = [(p, by_id[i]) for i, p in cached.payload['ranked'] if i in by_id]
            else:
                ranked = gemini_rank(data, found, api_key, model)
                SimilarAwardsCache.objects.update_or_create(tender=tender, defaults={'key': key, 'payload': {'ranked': [[a.pk, p] for p, a in ranked]}})
            hits, mode = ranked[:RESULTS], 'ai'
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            fallback = 'pomensko in besedilno ujemanje' if similarity else 'besedilno ujemanje'
            warning = f'AI razvrščanje ni uspelo ({exc if isinstance(exc, RuntimeError) else type(exc).__name__}). Prikazano je {fallback}.'
    if mode == 'text':
        hits = [(score, award) for score, award in found
                if (score >= VECTOR_THRESHOLD if award.pk in similarity else score >= TEXT_THRESHOLD)][:RESULTS]
    results = [serialize(score, award) for score, award in hits]
    message = '' if results else 'V zbirki ni dovolj podobnih preteklih oddaj.'
    return {**base, 'mode': mode, 'matching': 'semantic' if similarity else 'text', 'results': results,
            'summary': summarize(results), 'warning': warning, 'message': message}
