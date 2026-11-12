"""Expand search terms using verified passages from the current document index."""
import logging
import re
from collections import defaultdict

from .ai import ai_enabled, structured_call
from .deep_relevance import fold
from .document_index import search_passages
from .documents import active_documents
from .models import Document, DocumentChunk

log = logging.getLogger(__name__)
SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'suggestions': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
        'properties': {'term': {'type': 'string'}, 'passage': {'type': 'integer'},
                       'quote': {'type': 'string'}, 'reason': {'type': 'string'}},
        'required': ['term', 'passage', 'quote', 'reason']}}}, 'required': ['suggestions']}


def indexed_documents(tender_ids=None):
    # Reuse the same version/family rules as evidence validation, without loading full pages.
    query = Document.objects.select_related('tender').defer('pages')
    if tender_ids is not None:
        query = query.filter(tender_id__in=tender_ids)
    grouped = defaultdict(list)
    for doc in query.order_by('id').iterator():
        grouped[doc.tender_id].append(doc)
    result = []
    for docs in grouped.values():
        tender = docs[0].tender
        tender._document_metadata = docs
        result.extend(doc for doc in active_documents(tender, metadata_only=True)
                      if doc.indexed_content_id and doc.status == 'processed'
                      and doc.extraction.get('mode') != 'archive')
    return result


def matching_tenders(terms, tender_ids):
    return set(document_keyword_hits(terms, tender_ids))


def quote_around(text, term, radius=110):
    """Short excerpt of `text` around the first folded occurrence of `term`, with match offsets."""
    positions, folded = [], []
    for index, char in enumerate(text):
        for part in fold(char):
            positions.append(index)
            folded.append(part)
    found = ''.join(folded).find(term)
    if found < 0:
        excerpt = same_text(text[:2 * radius])
        return {'quote': excerpt, 'match_start': None, 'match_end': None}
    start, end = positions[found], positions[found + len(term) - 1] + 1
    left, right = max(0, start - radius), min(len(text), end + radius)
    # Do not cut words in half at the excerpt edges.
    while left > 0 and not text[left - 1].isspace() and start - left < radius + 25:
        left -= 1
    while right < len(text) and not text[right].isspace() and right - end < radius + 25:
        right += 1
    before, match, after = same_text(text[left:start]), text[start:end], same_text(text[end:right])
    prefix = ('… ' if left > 0 else '') + before + (' ' if before and text[start - 1].isspace() else '')
    suffix = (' ' if after and text[end].isspace() else '') + after + (' …' if right < len(text) else '')
    return {'quote': prefix + match + suffix, 'match_start': len(prefix), 'match_end': len(prefix) + len(match)}


def document_keyword_hits(terms, tender_ids):
    """First document passage per tender and search term: {tender_id: {term: evidence}}."""
    from django.db.models import BooleanField, ExpressionWrapper, Q
    terms = list(dict.fromkeys(fold(term) for term in terms if term))
    documents = indexed_documents(tender_ids)
    if not terms or not documents:
        return {}
    by_content = defaultdict(list)
    for doc in documents:
        by_content[doc.indexed_content_id].append(doc)
    flags = {f'k{index}': ExpressionWrapper(Q(normalized_text__contains=term), output_field=BooleanField())
             for index, term in enumerate(terms)}
    condition = Q()
    for term in terms:
        condition |= Q(normalized_text__contains=term)
    # One scan returns only ids and per-term flags; text is loaded just for the first hit.
    rows = (DocumentChunk.objects.filter(condition, content_id__in=by_content).annotate(**flags)
            .order_by('content_id', 'ordinal').values('id', 'content_id', *flags))
    first = {}
    for row in rows.iterator():
        for index, term in enumerate(terms):
            if row[f'k{index}']:
                first.setdefault((row['content_id'], term), row['id'])
    chunks = DocumentChunk.objects.in_bulk(set(first.values()))
    hits = defaultdict(dict)
    for (content_id, term), chunk_id in sorted(first.items(), key=lambda item: chunks[item[1]].ordinal):
        chunk = chunks[chunk_id]
        for doc in by_content[content_id]:
            if term in hits[doc.tender_id]:
                continue
            hits[doc.tender_id][term] = {'document_id': doc.pk, 'document_title': doc.title,
                'page': chunk.page if doc.extraction.get('format') == 'pdf' else None,
                'locator': chunk.locator, **quote_around(chunk.text, term)}
    return dict(hits)


def query_stems(query):
    # Profile matching truncates words to four letters, which turns "robot" into "robo"
    # and retrieves "robovi". Here the user typed the term, so keep almost the whole
    # word and only drop the Slovenian inflection ending.
    words = re.findall(r'\w+', fold(query))
    stems = set()
    for word in words:
        if len(word) >= 7:
            stems.add(word[:-2])
        elif len(word) >= 6:
            stems.add(word[:-1])
        elif len(word) >= 4 or (len(word) >= 2 and len(words) == 1):
            # Short words are only meaningful alone (e.g. an acronym), not "in"/"za" in a phrase.
            stems.add(word)
    return stems


def same_text(value):
    return ' '.join(value.split())


def expand(query):
    empty = {'suggestions': [], 'mode': 'unavailable'}
    documents = indexed_documents()
    passages, _ = search_passages(documents, {}, limit=30, terms=query_stems(query))
    if not passages:
        return {**empty, 'message': 'V indeksiranih dokumentih ni ustreznega konteksta za dodatne ključne besede.'}
    if not ai_enabled():
        return {**empty, 'message': 'AI trenutno ni povezan. Ključne besede ostajajo nespremenjene.'}
    try:
        answer = structured_call(SCHEMA,
            'Razširi ključne besede za iskanje javnih naročil. Izberi največ 8 kratkih izrazov, '
            'ki se DOBESEDNO pojavijo v priloženih odlomkih in so vsebinsko povezani z uporabnikovim iskanjem. '
            'Upoštevaj pomen celotnega izraza, ne zgolj skupne besede. Izberi strokovne sopomenke, '
            'poimenovanja opreme, storitev ali postopkov. Izpusti splošne razpisne izraze in nepovezane postavke. '
            'Ne ponavljaj vnesenih izrazov. passage je ničelni indeks odlomka; quote je kratek dobeseden citat '
            'iz tega odlomka, ki vsebuje term. reason na kratko v slovenščini pojasni povezavo z iskanjem. '
            'Če ni ustreznih izrazov, vrni prazen seznam.',
            {'query': query, 'passages': passages})
        seen = {fold(term.strip()) for term in query.split(',')}
        suggestions = []
        for item in answer['suggestions'][:20]:
            term, quote, position = item['term'].strip(), item['quote'].strip(), item['passage']
            if isinstance(position, bool) or not 0 <= position < len(passages):
                continue
            passage = passages[position]
            normalized = fold(term)
            if (not 2 <= len(term) <= 100 or ',' in term or '\n' in term or normalized in seen
                    or len(quote) < 8 or same_text(quote) not in same_text(passage['quote'])
                    or not re.search(r'(?<!\w)' + re.escape(normalized) + r'(?!\w)', fold(quote))):
                continue
            seen.add(normalized)
            suggestions.append({'term': term, 'reason': item['reason'][:500],
                'evidence': {**passage, 'quote': quote}})
            if len(suggestions) == 8:
                break
        return {'suggestions': suggestions, 'mode': 'live', 'message':
                'Dodani izrazi iz indeksiranih dokumentov.' if suggestions else
                'V dokumentih ni dodatnih izrazov s potrjenim citatom.'}
    except Exception as exc:
        log.warning('Keyword expansion unavailable: %s', type(exc).__name__)
        return {**empty, 'message': 'AI trenutno ni dosegljiv. Poskusite znova; ključne besede ostajajo nespremenjene.'}
