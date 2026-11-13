"""Expand search terms using verified passages from the current document index."""
import logging
import re
from collections import defaultdict

from .ai import ai_enabled, structured_call
from .deep_relevance import fold
from .document_index import search_passages
from .documents import active_documents
from .models import Document, DocumentChunk, PastAward

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


PASSAGES = 16
AWARDS = 6      # titles of past contracts are short and rich in trade terms
PER_DOCUMENT = 3
WINDOW = 1000   # characters of a passage shown to the model; shorter prompts answer much faster
POOL = 80
FUSION_K = 60
MAX_WORDS = 4   # longer terms are whole titles of one contract and match nothing else


def lexical_chunks(stems, limit):
    """Chunks containing every typed word (prefix match), best ranked first."""
    from django.contrib.postgres.search import SearchQuery, SearchRank
    terms = [t for t in stems if re.fullmatch(r'\w+', t)]
    if not terms:
        return []
    query = SearchQuery(' & '.join(f'{term}:*' for term in terms), config='simple', search_type='raw')
    return list(DocumentChunk.objects.filter(search_vector=query).annotate(rank=SearchRank('search_vector', query))
                .order_by('-rank', 'pk').values_list('pk', flat=True)[:limit])


def window(text, stems, size=WINDOW):
    """The part of a passage around the first typed word, or its beginning."""
    if len(text) <= size:
        return text
    folded = fold(text)
    hits = [folded.find(stem) for stem in stems if folded.find(stem) >= 0]
    start = max(0, min(hits) - size // 3) if hits else 0
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return text[start:start + size].strip()


def ranked_passages(query, limit=PASSAGES):
    """Passages by meaning and by all typed words, fused by rank; None when vectors are unavailable."""
    from .embeddings import enabled, nearest
    if not enabled() or not DocumentChunk.objects.filter(embedding__isnull=False).exists():
        return None
    stems = sorted(query_stems(query))
    scores = defaultdict(float)
    for rank, chunk in enumerate(nearest(DocumentChunk.objects.only('pk'), query, POOL)):
        scores[chunk.pk] += 1 / (FUSION_K + rank)
    for rank, pk in enumerate(lexical_chunks(stems, POOL)):
        scores[pk] += 1 / (FUSION_K + rank)
    chunks = DocumentChunk.objects.in_bulk(list(scores))
    # Only the documents behind the found passages are loaded, not the whole index.
    contents = {chunk.content_id for chunk in chunks.values()}
    tender_ids = set(Document.objects.filter(indexed_content_id__in=contents).values_list('tender_id', flat=True))
    by_content = {}
    for doc in indexed_documents(tender_ids):
        by_content.setdefault(doc.indexed_content_id, doc)
    passages, per_document = [], defaultdict(int)
    for pk in sorted(scores, key=lambda pk: -scores[pk]):
        chunk = chunks.get(pk)
        doc = by_content.get(chunk.content_id) if chunk else None
        if doc is None or per_document[doc.pk] >= PER_DOCUMENT:
            continue
        per_document[doc.pk] += 1
        passages.append({'document_id': doc.pk, 'document_title': doc.title,
            'page': chunk.page if doc.extraction.get('format') == 'pdf' else None,
            'locator': chunk.locator, 'quote': window(chunk.text, stems), 'matched_term': '',
            'document_url': f'/api/documents/{doc.pk}'})
        if len(passages) == limit:
            break
    return passages + award_passages(query)


def award_passages(query, limit=AWARDS):
    """Titles of the past contracts closest in meaning, cited by their award notice."""
    from .embeddings import nearest
    found = []
    # Award titles name the subject of a contract; phrasing the query the same way keeps short
    # queries (e.g. "cevna pošta") from matching unrelated postal or vehicle contracts.
    subject = f'Predmet javnega naročila: {query}'
    for award in nearest(PastAward.objects.only('pk', 'notice_id', 'published_on', 'data'), subject, limit * 3):
        d = award.data
        title = d.get('title') or ''
        if d.get('lot_title') and d['lot_title'] != title:
            title = f"{title} – {d['lot_title']}" if title else d['lot_title']
        if not title or any(p['quote'] == title for p in found):
            continue
        found.append({'document_id': '', 'document_title': f"Obvestilo o oddaji {d.get('notice_number') or award.notice_id}",
            'page': None, 'locator': ' · '.join(x for x in (d.get('buyer'), award.published_on.strftime('%d. %m. %Y') if award.published_on else '') if x),
            'quote': title[:WINDOW], 'matched_term': '',
            'document_url': f'https://www.enarocanje.si/#/pregled-objav/{award.notice_id}'})
        if len(found) == limit:
            break
    return found


def contains_words(text, term):
    """Whether folded `term` occurs in folded `text` as whole words."""
    return re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text) is not None


def source_of(quote, passages, position):
    """The passage that really contains the quote. Models often miscount the passage index or
    change letter case, so the claimed passage is tried first and then the others; a quote
    found nowhere is rejected."""
    wanted = fold(same_text(quote))
    order = ([position] if 0 <= position < len(passages) else []) + [i for i in range(len(passages)) if i != position]
    return next((passages[i] for i in order if wanted in fold(same_text(passages[i]['quote']))), None)


def expand(query):
    empty = {'suggestions': [], 'mode': 'unavailable'}
    try:
        passages = ranked_passages(query)
    except Exception as exc:  # The vector index is an improvement, never a requirement.
        log.warning('Vector passages unavailable: %s', type(exc).__name__)
        passages = None
    if passages is None:
        passages, _ = search_passages(indexed_documents(), {}, limit=30, terms=query_stems(query))
    if not passages:
        return {**empty, 'message': 'V indeksiranih dokumentih ni ustreznega konteksta za dodatne ključne besede.'}
    if not ai_enabled():
        return {**empty, 'message': 'AI trenutno ni povezan. Ključne besede ostajajo nespremenjene.'}
    try:
        answer = structured_call(SCHEMA,
            'Razširi ključne besede za iskanje javnih naročil. Izberi največ 8 kratkih izrazov (1 do 3 besede), '
            'ki se DOBESEDNO pojavijo v priloženih odlomkih in so vsebinsko povezani z uporabnikovim iskanjem. '
            'Upoštevaj pomen celotnega izraza, ne zgolj skupne besede. Izberi strokovne sopomenke, '
            'poimenovanja opreme, storitev ali postopkov. Izraz je samo jedro pojma: iz naslova, kot je '
            '"vzdrževanje cevne zračne pošte", vzemi "cevne zračne pošte"; izpusti dejanja (dobava, vzdrževanje, '
            'dograditev, nadgradnja, izvedba), kraje in naročnike, sicer izraz ne najde novih razpisov. '
            'Izpusti splošne razpisne izraze in nepovezane postavke. '
            'Ne ponavljaj vnesenih izrazov. passage je ničelni indeks odlomka; quote je kratek dobeseden citat '
            'iz tega odlomka, ki vsebuje term. reason na kratko v slovenščini pojasni povezavo z iskanjem. '
            'Če ni ustreznih izrazov, vrni prazen seznam.',
            {'query': query, 'passages': passages}, reasoning='low')
        seen = {fold(term.strip()) for term in query.split(',') if term.strip()}
        suggestions = []
        for item in answer['suggestions'][:20]:
            term, quote, position = item['term'].strip(), item['quote'].strip(), item['passage']
            if isinstance(position, bool) or not isinstance(position, int):
                continue
            passage = source_of(quote, passages, position)
            normalized = fold(term)
            if (passage is None or not 2 <= len(term) <= 100 or len(term.split()) > MAX_WORDS
                    or ',' in term or '\n' in term or normalized in seen
                    or len(quote) < 8 or not contains_words(fold(quote), normalized)
                    # "sistema cevne zračne pošte" finds only what "cevne zračne pošte" already finds.
                    or any(contains_words(normalized, known) for known in seen)):
                continue
            seen.add(normalized)
            suggestions.append({'term': term, 'reason': item['reason'][:500],
                'evidence': {**passage, 'quote': quote}})
        # Keep the shortest verified phrase regardless of the model's response order.
        suggestions = [item for item in suggestions if not any(
            other is not item and contains_words(fold(item['term']), fold(other['term']))
            for other in suggestions)][:8]
        return {'suggestions': suggestions, 'mode': 'live', 'message':
                'Dodani izrazi iz indeksiranih dokumentov.' if suggestions else
                'V dokumentih ni dodatnih izrazov s potrjenim citatom.'}
    except Exception as exc:
        log.warning('Keyword expansion unavailable: %s', type(exc).__name__)
        return {**empty, 'message': 'AI trenutno ni dosegljiv. Poskusite znova; ključne besede ostajajo nespremenjene.'}
