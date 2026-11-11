"""Offline comparison of content-relevance approaches on a hand-labelled set.

Compares the current keyword rules (matching.content_match), a general LLM with an
enum schema (ai.structured_call) and the Gemini Decisions API. Only fictional eval
profiles are sent to providers; tender data is public PJN metadata. Nothing here
changes what the app shows to users.
"""
import csv
import json
import os
from pathlib import Path

import requests

from .matching import content_match

LABELS = ['neprimeren', 'delno', 'primeren']  # index == rubric level
LABEL_ALIASES = {'n': 'neprimeren', '0': 'neprimeren', 'd': 'delno', '1': 'delno', 'p': 'primeren', '2': 'primeren'}
RUBRIC = [
    'neprimeren: predmet naročila ni povezan z dejavnostjo podjetja; podjetje ga ne bi moglo izvesti.',
    'delno: sorodno področje ali le del naročila spada v dejavnost podjetja; prijava bi zahtevala partnerja ali podizvajalca.',
    'primeren: predmet naročila je jedrna dejavnost podjetja; podjetje bi ga lahko izvedlo samo.',
]
LEVEL_TO_LABEL = {'low': 'neprimeren', 'medium': 'delno', 'high': 'primeren'}
KIND_LABELS = {'services': 'storitve', 'goods': 'blago', 'works': 'gradnje'}
DEFAULT_FILE = Path(__file__).resolve().parent.parent / 'eval' / 'relevance_labels.csv'
FIELDS = ['profile_id', 'tender_id', 'label', 'note', 'profile', 'title', 'kind', 'cpv', 'topics', 'summary']
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/decisions'
GEMINI_MAX_QUESTIONS = 1000

# Fictional companies only: the comparison must never send a real company profile.
EVAL_PROFILES = {
    'lumina': {
        'name': 'Lumina digital (izmišljeno podjetje, demo profil)',
        'activity': 'Razvoj programske opreme in digitalnih rešitev',
        'description': 'Razvijamo spletne in mobilne aplikacije, IoT platforme ter podatkovne rešitve. Povezujemo senzorje in poslovne sisteme ter avtomatiziramo procese.',
        'expertise': ['Spletne platforme', 'IoT in integracije', 'AI in podatki'],
        'keywords': ['razvoj programske opreme', 'spletna platforma', 'IoT', 'integracija', 'podatkovna analitika', 'satelitski podatki'],
        'technologies': ['React', 'Django', 'ASP.NET', 'Vue.js', 'Nuxt.js', 'WebSocket', 'Docker'],
    },
    'cestograd': {
        'name': 'Cestograd (izmišljeno podjetje)',
        'activity': 'Gradnja cest in komunalne infrastrukture',
        'description': 'Izvajamo nizke gradnje: obnove vozišč, sanacije cest in plazov, ureditve ulic, pločnikov in parkirišč ter gradnjo komunalnih vodov.',
        'expertise': ['Nizke gradnje', 'Sanacije cest in plazov', 'Komunalna infrastruktura'],
        'keywords': ['obnova vozišča', 'gradbena dela', 'sanacija', 'vodovod', 'kanalizacija'],
        'technologies': [],
    },
    'tiskarna': {
        'name': 'Tiskarna Papirnik (izmišljeno podjetje)',
        'activity': 'Tiskarske storitve in prodaja pisarniškega materiala',
        'description': 'Tiskamo publikacije, obrazce in promocijsko gradivo ter dobavljamo pisarniški material, papir in tonerje.',
        'expertise': ['Tisk', 'Pisarniški material'],
        'keywords': ['tiskarske storitve', 'pisarniški material', 'papir', 'tonerji', 'dobava'],
        'technologies': [],
    },
    'optika': {
        'name': 'Optika Net (izmišljeno podjetje)',
        'activity': 'Gradnja in vzdrževanje telekomunikacijskih omrežij',
        'description': 'Gradimo in vzdržujemo optična omrežja, izvajamo optične povezave in zagotavljamo podatkovne povezave za daljinsko odčitavanje števcev.',
        'expertise': ['Optična omrežja', 'Telekomunikacije'],
        'keywords': ['optične povezave', 'telekomunikacije', 'prenos podatkov', 'omrežje'],
        'technologies': ['GPON', 'LTE-M'],
    },
}


def normalize_label(value):
    value = (value or '').strip().lower()
    value = LABEL_ALIASES.get(value, value)
    if value and value not in LABELS:
        raise ValueError(f'Neznana oznaka »{value}«; dovoljene so {", ".join(LABELS)}.')
    return value


def profile_text(profile):
    parts = [f"Podjetje: {profile['name']}", f"Dejavnost: {profile['activity']}", f"Opis: {profile['description']}",
             'Področja: ' + ', '.join(profile['expertise']), 'Ključne besede: ' + ', '.join(profile['keywords'])]
    if profile['technologies']:
        parts.append('Tehnologije: ' + ', '.join(profile['technologies']))
    return '\n'.join(parts)


def tender_text(row):
    return '\n'.join([f"Naslov: {row['title']}", f"Vrsta: {KIND_LABELS.get(row['kind'], row['kind'])}",
                      f"CPV: {row['cpv']} ({row['topics']})", f"Opis: {row['summary']}"])


# --- Labelled set -----------------------------------------------------------------

def read_rows(path):
    with open(path, newline='', encoding='utf-8-sig') as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=';,')
        rows = list(csv.DictReader(handle, dialect=dialect))
    for i, row in enumerate(rows, start=2):
        try:
            row['label'] = normalize_label(row.get('label'))
        except ValueError as exc:
            raise ValueError(f'Vrstica {i}: {exc}') from None
    return rows


def write_rows(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Semicolon + BOM opens correctly in Excel with Slovenian locale and in Google Sheets.
    with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter=';', lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def export_rows(tenders, path, profile_ids=None):
    """Build profile x real-tender rows; existing labels and notes are preserved."""
    existing = {(r['profile_id'], r['tender_id']): r for r in read_rows(path)} if Path(path).exists() else {}
    rows = []
    for profile_id in profile_ids or EVAL_PROFILES:
        profile = EVAL_PROFILES[profile_id]
        for tender in tenders:
            data = tender.data
            if data.get('source_type') != 'real':
                continue  # Demo tenders were written for the demo profile and would flatter the rules.
            old = existing.get((profile_id, tender.pk), {})
            rows.append({
                'profile_id': profile_id, 'tender_id': tender.pk,
                'label': old.get('label', ''), 'note': old.get('note', ''),
                'profile': profile['activity'], 'title': data.get('title', ''), 'kind': data.get('kind', ''),
                'cpv': ' '.join(data.get('cpv', [])), 'topics': ' | '.join(data.get('topics', [])),
                'summary': ' '.join((data.get('summary') or '').split())[:600],
            })
    kept = {(r['profile_id'], r['tender_id']) for r in rows}
    # Labels for tenders no longer in this database are kept, not silently dropped.
    rows += [r for key, r in existing.items() if key not in kept]
    write_rows(path, rows)
    return rows


# --- Approaches ---------------------------------------------------------------------

def predict_rules(rows):
    out = {}
    for row in rows:
        data = {'title': row['title'], 'summary': row['summary'], 'kind': row['kind'], 'source_type': 'real',
                'topics': [t.strip() for t in row['topics'].split('|') if t.strip()], 'technologies': []}
        level, score, _ = content_match(data, EVAL_PROFILES[row['profile_id']])
        out[(row['profile_id'], row['tender_id'])] = {'label': LEVEL_TO_LABEL[level], 'score': score}
    return out


LLM_SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'answers': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
        'properties': {'tender_id': {'type': 'string'}, 'label': {'type': 'string', 'enum': LABELS}},
        'required': ['tender_id', 'label']}}}, 'required': ['answers']}


def predict_llm(rows):
    from .ai import structured_call
    out = {}
    for profile_id, group in group_by_profile(rows).items():
        result = structured_call(LLM_SCHEMA,
            'Za vsak razpis oceni samo vsebinsko primernost predmeta naročila za podjetje iz profila. '
            'Ne presojaj pogojev, vrednosti, lokacije ali roka. Uporabi natanko eno oznako:\n' + '\n'.join(RUBRIC) +
            '\nVrni odgovor za vsak tender_id natanko enkrat.',
            {'profile': profile_text(EVAL_PROFILES[profile_id]),
             'tenders': [{'tender_id': r['tender_id'], 'text': tender_text(r)} for r in group]})
        allowed = {r['tender_id'] for r in group}
        for answer in result['answers']:
            if answer['tender_id'] in allowed:
                out[(profile_id, answer['tender_id'])] = {'label': answer['label']}
    return out


def gemini_request(profile_id, group, model):
    instructions = ('Kako vsebinsko primeren je spodnji razpis za podjetje iz vhoda? Presojaj samo predmet naročila, '
                    'ne pogojev, vrednosti, lokacije ali roka.\n\n')
    return {
        'model': model if model.startswith('models/') else f'models/{model}',
        'input': profile_text(EVAL_PROFILES[profile_id]),
        # Question IDs must be 1-64 chars of [A-Za-z0-9_-]; tender IDs are not, so use positions.
        'questions': {f'q{i}': {'type': 'score', 'instructions': instructions + tender_text(r), 'criteria': RUBRIC}
                      for i, r in enumerate(group)},
    }


def predict_gemini(rows, api_key, model):
    out = {}
    for profile_id, group in group_by_profile(rows).items():
        for start in range(0, len(group), GEMINI_MAX_QUESTIONS):
            chunk = group[start:start + GEMINI_MAX_QUESTIONS]
            body = gemini_request(profile_id, chunk, model)
            response = requests.post(GEMINI_URL, json=body, timeout=(5, 60),
                                     headers={'x-goog-api-key': api_key, 'Content-Type': 'application/json'})
            if response.status_code != 200:
                # Body may echo the request; status code only, never the key.
                raise RuntimeError(f'Gemini Decisions API je vrnil status {response.status_code}.')
            data = response.json()
            blocked = (data.get('prompt_feedback') or data.get('promptFeedback') or {})
            if blocked.get('block_reason') or blocked.get('blockReason'):
                raise RuntimeError('Gemini Decisions API je zavrnil vhod (prompt feedback).')
            for qid, answer in (data.get('answers') or {}).items():
                index = int(qid[1:]) if qid[:1] == 'q' and qid[1:].isdigit() else -1
                if not 0 <= index < len(chunk):
                    continue
                tender_id = chunk[index]['tender_id']
                probs = [float(answer.get('probabilities', {}).get(str(i), 0.0)) for i in range(len(LABELS))]
                out[(profile_id, tender_id)] = {'label': LABELS[max(range(len(LABELS)), key=probs.__getitem__)],
                                                'probabilities': probs, 'confidence': answer.get('confidence'),
                                                'score': answer.get('score')}
    return out


def group_by_profile(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row['profile_id'], []).append(row)
    return groups


# --- Metrics ------------------------------------------------------------------------

def metrics(rows, predictions):
    labelled = [r for r in rows if r['label']]
    pairs = [(r['label'], predictions[(r['profile_id'], r['tender_id'])]) for r in labelled
             if (r['profile_id'], r['tender_id']) in predictions]
    confusion = {t: {p: 0 for p in LABELS} for t in LABELS}
    for truth, pred in pairs:
        confusion[truth][pred['label']] += 1
    n = len(pairs)
    correct = sum(confusion[label][label] for label in LABELS)
    f1s = []
    for label in LABELS:
        tp = confusion[label][label]
        predicted = sum(confusion[t][label] for t in LABELS)
        actual = sum(confusion[label].values())
        precision = tp / predicted if predicted else 0.0
        recall = tp / actual if actual else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    predicted_fit = sum(confusion[t]['primeren'] for t in LABELS)
    actual_fit = sum(confusion['primeren'].values())
    result = {
        'labelled': len(labelled), 'predicted': n,
        'accuracy': correct / n if n else None,
        'macro_f1': sum(f1s) / len(f1s) if n else None,
        # "Recommended" share that is truly a fit, and share of true fits that were found.
        'fit_precision': confusion['primeren']['primeren'] / predicted_fit if predicted_fit else None,
        'fit_recall': confusion['primeren']['primeren'] / actual_fit if actual_fit else None,
        # Opposite-end mistakes: recommending an unrelated tender or discarding a core one.
        'severe_errors': confusion['neprimeren']['primeren'] + confusion['primeren']['neprimeren'],
        'confusion': confusion,
    }
    probabilistic = [(truth, pred) for truth, pred in pairs if pred.get('probabilities')]
    if probabilistic:
        result['brier'] = sum(sum((p - (1.0 if LABELS[i] == truth else 0.0)) ** 2 for i, p in enumerate(pred['probabilities']))
                              for truth, pred in probabilistic) / len(probabilistic)
        result['mean_confidence'] = sum(max(pred['probabilities']) for _, pred in probabilistic) / len(probabilistic)
    return result


def run(rows, approaches, gemini_key=None, gemini_model='gemini-decision-1'):
    """Returns {approach: {'metrics': ..., 'predictions': ...} | {'skipped': reason}}."""
    from .ai import ai_enabled
    labelled = [r for r in rows if r['label']]
    results = {}
    for approach in approaches:
        if approach == 'rules':
            predictions = predict_rules(labelled)
        elif approach == 'llm':
            if not ai_enabled():
                results[approach] = {'skipped': 'ni OPENROUTER_API_KEY ali OPENAI_API_KEY'}
                continue
            predictions = predict_llm(labelled)
        elif approach == 'gemini':
            if not gemini_key:
                results[approach] = {'skipped': 'ni GEMINI_API_KEY'}
                continue
            predictions = predict_gemini(labelled, gemini_key, gemini_model)
        else:
            raise ValueError(f'Neznan pristop »{approach}«.')
        results[approach] = {'metrics': metrics(labelled, predictions),
                             'predictions': {f'{p}/{t}': v for (p, t), v in predictions.items()}}
    return results


def gemini_settings():
    return os.environ.get('GEMINI_API_KEY') or None, os.environ.get('GEMINI_DECISION_MODEL') or 'gemini-decision-1'


def dumps(results):
    return json.dumps(results, ensure_ascii=False, indent=2)
