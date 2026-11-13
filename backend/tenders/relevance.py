"""Cached Gemini Decision 1 content fit for the active company and its tenders.

The model scores subject relevance only. Eligibility, document evidence and final
recommendations remain deterministic in matching.py. No company identity,
registration number, address, references or document text are sent to Google.
"""
import hashlib
import json
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import requests
from django.utils import timezone

from .models import RelevanceCache


log = logging.getLogger(__name__)
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/decisions'
RUBRIC = [
    'Neprimeren: predmet naročila ni povezan z dejavnostjo podjetja in ga podjetje ne bi moglo izvesti.',
    'Delno primeren: soroden je le del naročila ali bi podjetje za predmet potrebovalo partnerja.',
    'Primeren: predmet naročila je jedrna dejavnost podjetja in ga podjetje vsebinsko lahko izvede samo.',
]
CHUNK_SIZE = 40
# A profile change re-scores every tender (~27 batches); it runs in the background (resolve_matches_nowait).
PARALLEL_BATCHES = 8
RETRY_AFTER = timedelta(minutes=15)
CACHE_TTL = timedelta(days=60)


def settings():
    return os.environ.get('GEMINI_API_KEY') or None, os.environ.get('GEMINI_DECISION_MODEL') or 'gemini-decision-1'


def profile_input(profile):
    """Send capabilities relevant to subject fit, without identifying the company."""
    fields = [('Dejavnost', profile.get('activity', '')), ('Opis', profile.get('description', '')),
              ('Področja', ', '.join(profile.get('expertise', []))),
              ('Ključne besede', ', '.join(profile.get('keywords', []))),
              ('Tehnologije', ', '.join(profile.get('technologies', [])))]
    return '\n'.join(f'{label}: {str(value)[:1200]}' for label, value in fields)


def tender_input(data):
    return ('Naslov: ' + str(data.get('title') or '')[:400] + '\n'
            'Vrsta: ' + str(data.get('kind') or '')[:30] + '\n'
            'CPV: ' + ', '.join(data.get('cpv') or [])[:200] + '\n'
            'Predmet: ' + str(data.get('summary') or '')[:1200])


def fingerprint(profile, data, model):
    payload = [profile_input(profile), tender_input(data), model, RUBRIC]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def score_answer(answer):
    if not isinstance(answer, dict):
        raise ValueError('Manjka odgovor modela.')
    values = answer.get('probabilities')
    if not isinstance(values, dict):
        raise ValueError('Manjkajo verjetnosti modela.')
    probabilities = [values.get(str(i)) for i in range(3)]
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1
           for p in probabilities) or not 0.98 <= sum(probabilities) <= 1.02:
        raise ValueError('Neveljavne verjetnosti modela.')
    unsuitable, partial, suitable = probabilities
    # Conservative thresholds from the branch's award-based evaluation. Ambiguity stays in review.
    if unsuitable >= 0.8:
        level = 'low'
    elif suitable >= 0.5:
        level = 'high'
    else:
        level = 'medium'
    expected = round(100 * (suitable + 0.5 * partial))
    lower, upper = {'low': (0, 39), 'medium': (40, 69), 'high': (70, 99)}[level]
    score = max(lower, min(upper, expected))
    reason = {
        'low': 'AI je predmet razpisa glede na opis dejavnosti in znanj podjetja ocenil kot vsebinsko neustrezen.',
        'medium': 'AI je pri predmetu razpisa prepoznal delno ali negotovo ujemanje z dejavnostjo podjetja.',
        'high': 'AI je predmet razpisa ocenil kot jedrno področje dejavnosti podjetja.',
    }[level]
    return {'mode': 'gemini', 'level': level, 'score': score,
            'reasons': [reason, 'Presoja uporablja predmet razpisa in opis sposobnosti v profilu; pogoje preverite ločeno.'],
            'probabilities': {'unsuitable': unsuitable, 'partial': partial, 'suitable': suitable}}


def request_batch(tenders, profile, api_key, model):
    body = {
        'model': model if model.startswith('models/') else f'models/{model}',
        'input': profile_input(profile),
        'questions': {f'q{i}': {
            'type': 'score',
            'instructions': 'Kako vsebinsko primeren je razpis za opisane sposobnosti podjetja? Presojaj le predmet '
                            'naročila, ne referenc, pogojev, vrednosti, lokacije ali roka.\n\n' + tender_input(tender.data),
            'criteria': RUBRIC,
        } for i, tender in enumerate(tenders)},
    }
    response = requests.post(GEMINI_URL, json=body, timeout=(5, 45),
                             headers={'x-goog-api-key': api_key, 'Content-Type': 'application/json'})
    if response.status_code != 200:
        raise ValueError(f'HTTP {response.status_code}')
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get('answers'), dict):
        raise ValueError('Neveljaven odgovor modela.')
    blocked = data.get('prompt_feedback') or data.get('promptFeedback') or {}
    if isinstance(blocked, dict) and (blocked.get('block_reason') or blocked.get('blockReason')):
        raise ValueError('Vhod je bil zavrnjen.')
    return {tender.pk: score_answer(data['answers'].get(f'q{i}')) for i, tender in enumerate(tenders)}


def resolve_matches(tenders, profile, cached_only=False):
    """Return Gemini results or labelled rule fallbacks, batching uncached inputs."""
    tenders = list(tenders)
    api_key, model = settings()
    if not api_key or not tenders:
        return {tender.pk: {'mode': 'rules'} for tender in tenders}
    results, missing = lookup(tenders, profile, model)
    if cached_only:
        return {**results, **{tender.pk: {'mode': 'rules'} for tender, _ in missing}}
    batches = [missing[start:start + CHUNK_SIZE] for start in range(0, len(missing), CHUNK_SIZE)]

    def decide(batch):
        # Network only: tender.data is already loaded, so worker threads never touch the database.
        try:
            return request_batch([tender for tender, _ in batch], profile, api_key, model)
        except (requests.RequestException, ValueError, TypeError) as exc:
            log.warning('Gemini relevance unavailable: %s', type(exc).__name__)
            return {tender.pk: {'mode': 'rules', 'warning': 'AI presoja trenutno ni dosegljiva; uporabljena so pravila.'}
                    for tender, _ in batch}

    if len(batches) > 1:
        with ThreadPoolExecutor(max_workers=min(PARALLEL_BATCHES, len(batches))) as pool:
            decided_batches = list(pool.map(decide, batches))
    else:
        decided_batches = [decide(batch) for batch in batches]
    rows = []
    now = timezone.now()
    for batch, decided in zip(batches, decided_batches):
        for tender, key in batch:
            results[tender.pk] = decided[tender.pk]
            rows.append(RelevanceCache(tender=tender, key=key, payload=decided[tender.pk], updated_at=now))
    if rows:
        RelevanceCache.objects.bulk_create(rows, batch_size=500, update_conflicts=True, unique_fields=['tender', 'key'],
                                           update_fields=['payload', 'updated_at'])
        # Rows of edited profiles and changed tenders are never read again.
        RelevanceCache.objects.filter(updated_at__lt=now - CACHE_TTL).delete()
    return results


def lookup(tenders, profile, model):
    """Split tenders into usable cached assessments and (tender, fingerprint) pairs that need scoring."""
    keys = {tender.pk: fingerprint(profile, tender.data, model) for tender in tenders}
    cached = {(row.tender_id, row.key): row for row in RelevanceCache.objects.filter(
        tender_id__in=list(keys), key__in=set(keys.values()))}
    results, missing = {}, []
    now = timezone.now()
    for tender in tenders:
        row = cached.get((tender.pk, keys[tender.pk]))
        if row and (row.payload.get('mode') == 'gemini' or
                    (row.payload.get('mode') == 'rules' and now - row.updated_at < RETRY_AFTER)):
            results[tender.pk] = row.payload
        else:
            missing.append((tender, keys[tender.pk]))
    return results, missing


def resolve_matches_nowait(tenders, profile):
    """Cached assessments now; uncached tenders get rules and are scored in the background.

    Returns (results, pending). A profile edit changes every fingerprint, and scoring ~1000
    tenders took tens of seconds, so list requests no longer wait for Gemini.
    """
    from django.conf import settings as django_settings
    from .background import run_once
    tenders = list(tenders)
    api_key, model = settings()
    if not api_key or not tenders or django_settings.BACKGROUND_TASKS_INLINE:
        return resolve_matches(tenders, profile), False
    results, missing = lookup(tenders, profile, model)
    if not missing:
        return results, False
    todo = [tender for tender, _ in missing]
    key = hashlib.sha256(json.dumps([profile_input(profile), model, RUBRIC], ensure_ascii=False).encode()).hexdigest()[:16]
    run_once(f'relevance:{key}', lambda: resolve_matches(todo, profile))
    return {**results, **{tender.pk: {'mode': 'rules'} for tender in todo}}, True
