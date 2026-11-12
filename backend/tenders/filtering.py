from datetime import date, datetime
from rest_framework.exceptions import ValidationError
from .matching import text_normalize
from .seed import today


ARRAY_FIELDS = {'cpv', 'kinds', 'buyers', 'regions', 'levels', 'condition_states', 'statuses', 'source_types'}
BOOL_FIELDS = {'include_unknown', 'only_new', 'only_updates', 'only_following', 'include_partner_opportunities'}
NUMBER_FIELDS = {'min_value', 'max_value', 'min_days', 'min_score'}
DATE_FIELDS = {'published_from', 'published_to', 'deadline_from', 'deadline_to'}
TEXT_FIELDS = {'q', 'exclude', 'view', 'sort'}


def validate_filters(raw):
    if not isinstance(raw, dict):
        raise ValidationError('Filtri morajo biti objekt.')
    filters = {}
    for key, value in raw.items():
        if value is None or value == '':
            continue
        if key in ARRAY_FIELDS:
            if isinstance(value, str):
                value = [v.strip() for v in value.split(',') if v.strip()]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value) or len(value) > 100:
                raise ValidationError({key: 'Pričakovan je seznam vrednosti.'})
            filters[key] = value
        elif key in BOOL_FIELDS:
            if isinstance(value, bool):
                filters[key] = value
            elif str(value).lower() in ['true', 'false', '1', '0']:
                filters[key] = str(value).lower() in ['true', '1']
            else:
                raise ValidationError({key: 'Pričakovana je logična vrednost.'})
        elif key in NUMBER_FIELDS:
            try:
                if isinstance(value, bool):
                    raise ValueError()
                number = float(value)
                if number < 0 or number > 1e12 or number != number:
                    raise ValueError()
                if key == 'min_score' and (number > 100 or number != int(number)):
                    raise ValueError()
                filters[key] = number
            except (ValueError, TypeError):
                raise ValidationError({key: 'Vnesite veljavno nenegativno število.'})
        elif key in DATE_FIELDS:
            try:
                filters[key] = date.fromisoformat(value).isoformat()
            except (ValueError, TypeError):
                raise ValidationError({key: 'Datum mora biti v obliki YYYY-MM-DD.'})
        elif key in TEXT_FIELDS:
            if not isinstance(value, str) or len(value) > 2000:
                raise ValidationError({key: 'Besedilo je predolgo ali neveljavno.'})
            filters[key] = value
    if filters.get('min_value', 0) > filters.get('max_value', 1e12):
        raise ValidationError('Najnižja vrednost ne sme presegati najvišje.')
    for prefix in ('published', 'deadline'):
        if filters.get(prefix + '_from', '') > filters.get(prefix + '_to', '9999-12-31'):
            raise ValidationError('Začetni datum ne sme biti po končnem datumu.')
    return filters


def search_terms(query):
    """Comma separated search terms as typed, deduplicated by their normalized form."""
    terms = {}
    for term in (query or '').split(','):
        term = ' '.join(term.split())
        if term:
            terms.setdefault(text_normalize(term), term)
    return terms


METADATA_FIELDS = [('title', 'naslovu'), ('summary', 'opisu'), ('buyer', 'naročniku'),
                   ('topics', 'področjih'), ('technologies', 'tehnologijah')]


def keyword_matches(tender, query, document_hits):
    """Every search term present in a tender, with a document citation where one exists."""
    found = []
    for normalized, term in search_terms(query).items():
        evidence = document_hits.get(normalized)
        fields = []
        for field, label in METADATA_FIELDS:
            value = tender.get(field) or ''
            if normalized in text_normalize(' '.join(value) if isinstance(value, list) else value):
                fields.append(label)
        if evidence or fields:
            found.append({'term': term, 'fields': fields, 'evidence': evidence})
    return found


def apply_filters(tenders, filters, keyword_hits=None):
    """Filter and sort tenders. Pass a dict as keyword_hits to receive document matches per tender."""
    filters = validate_filters(filters)
    include_unknown = filters.get('include_unknown', True)
    view = filters.get('view', 'recommended')
    output = []
    words = [text_normalize(w.strip()) for w in filters.get('q', '').split(',') if w.strip()]
    document_matches = {}
    if words:
        from .keyword_expansion import document_keyword_hits
        document_matches = document_keyword_hits(words, [t['id'] for t in tenders])
        if keyword_hits is not None:
            keyword_hits.update(document_matches)
    for tender in tenders:
        if view == 'recommended':
            partner_opportunity = filters.get('include_partner_opportunities') and any(c['status'] == 'unmet' for c in tender['match']['conditions'])
            if tender['status'] != 'open' or tender['match']['level'] == 'low' or (tender['match']['recommendation'] == 'unsuitable' and not partner_opportunity):
                continue
        if tender['match']['score'] < filters.get('min_score', 0):
            continue
        if (view == 'following' or filters.get('only_following')) and not tender['following']:
            continue
        if filters.get('only_new') and not tender['is_new']:
            continue
        if filters.get('only_updates') and not tender['has_update']:
            continue
        haystack = text_normalize(' '.join([tender['title'], tender.get('summary', ''), tender['buyer']] + tender.get('topics', []) + tender.get('technologies', [])))
        excluded = [text_normalize(w.strip()) for w in filters.get('exclude', '').split(',') if w.strip()]
        if words and tender['id'] not in document_matches and not any(word in haystack for word in words):
            continue
        if any(word in haystack for word in excluded):
            continue
        if filters.get('cpv') and not any(code.startswith(query.split('-')[0].rstrip('0')) for code in tender.get('cpv', []) for query in filters['cpv']):
            continue
        if any(filters.get(key) and tender.get(field) not in filters[key] for key, field in [('kinds', 'kind'), ('buyers', 'buyer'), ('regions', 'region'), ('statuses', 'status'), ('source_types', 'source_type')]):
            continue
        if filters.get('levels') and tender['match']['level'] not in filters['levels']:
            continue
        if filters.get('condition_states'):
            states = {c['status'] for c in tender['match']['conditions']} or {'unknown'}
            if not states.intersection(filters['condition_states']):
                continue
        value = tender.get('value')
        if 'min_value' in filters or 'max_value' in filters:
            if value is None and not include_unknown:
                continue
            if value is not None and not (filters.get('min_value', 0) <= value <= filters.get('max_value', float('inf'))):
                continue
        keep = True
        for prefix, field in [('published', 'published_at'), ('deadline', 'deadline')]:
            bounded = prefix + '_from' in filters or prefix + '_to' in filters or (prefix == 'deadline' and 'min_days' in filters)
            if not bounded:
                continue
            raw = tender.get(field)
            try:
                parsed = date.fromisoformat(raw[:10]) if raw else None
            except ValueError:
                parsed = None
            if parsed is None:
                keep = include_unknown
            else:
                keep = filters.get(prefix + '_from', '0001-01-01') <= parsed.isoformat() <= filters.get(prefix + '_to', '9999-12-31')
                if prefix == 'deadline' and 'min_days' in filters:
                    keep = keep and (parsed - today()).days >= filters['min_days']
            if not keep:
                break
        if keep:
            output.append(tender)
    sort = filters.get('sort', 'match')
    if sort == 'deadline':
        output.sort(key=lambda t: t.get('deadline') or '9999')
    elif sort == 'newest':
        output.sort(key=lambda t: t.get('published_at') or '', reverse=True)
    elif sort == 'value':
        output.sort(key=lambda t: t.get('value') if t.get('value') is not None else -1, reverse=True)
    else:
        output.sort(key=lambda t: (-t['match']['score'], t.get('deadline') or '9999'))
    return output
