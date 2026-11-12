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
    from django.db.models import Q
    documents = indexed_documents(tender_ids)
    if not documents:
        return set()
    condition = Q()
    for term in terms:
        condition |= Q(normalized_text__contains=fold(term))
    contents = set(DocumentChunk.objects.filter(condition,
        content_id__in={doc.indexed_content_id for doc in documents}).values_list('content_id', flat=True))
    return {doc.tender_id for doc in documents if doc.indexed_content_id in contents}


def expand(query):
    empty = {'suggestions': [], 'mode': 'unavailable'}
    documents = indexed_documents()
    retrieval_query = query.upper() if re.fullmatch(r'[a-zA-Z]{2,3}', query) else query
    passages, _ = search_passages(documents, {'keywords': [retrieval_query]}, limit=30)
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
                    or len(quote) < 8 or quote not in passage['quote']
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
