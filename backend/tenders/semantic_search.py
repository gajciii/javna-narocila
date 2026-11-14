"""Tenders that match a search term by meaning although their text does not contain it.

Similarity scales differ a lot between queries (measured on production, 1,078 tenders,
text-embedding-3-large): for "čiščenje prostorov" relevant tenders reach 0.65, for
"videonadzor" they stay below 0.46, and for "cevna pošta", which no tender is about, an
unrelated one still reaches 0.51. A tender therefore has to pass an absolute floor and also
be close to the best match of that query, so a query without good matches adds nothing.

Generic queries ("svetovanje pri javnem naročanju", "storitve") resemble every tender about
equally, so their best match barely stands out from the median (0.11-0.16, against 0.21-0.29
for specific subjects); such queries add nothing either.
"""
import logging
import statistics
import time

from .models import Tender

log = logging.getLogger(__name__)

MIN_SIMILARITY = 0.52  # above the best unrelated match seen in production (0.51)
MARGIN = 0.06          # only tenders nearly as close as the query's best match
DISTINCT = 0.19        # how far the best match must stand out from the median tender
PER_TERM = 20
MIN_TERM = 4           # acronyms and very short words embed without a stable meaning
PAUSE = 60             # seconds without semantic search after the provider fails

_down_until = 0.0


def semantic_matches(terms, tender_ids):
    """{tender_id: {'term', 'similarity'}} for tenders close in meaning to a term; {} when unavailable.

    Searching must never fail or stall because of the embedding provider: on an error the
    word search is used alone and the provider is not asked again for a minute.
    """
    global _down_until
    from .embeddings import enabled, similarities
    terms = [term for term in terms if len(term.strip()) >= MIN_TERM]
    if not terms or not tender_ids or not enabled() or time.monotonic() < _down_until:
        return {}
    found = {}
    for term in terms:
        try:
            scores = similarities(Tender, term, tender_ids)
        except Exception as exc:
            log.warning('Semantic search unavailable: %s', type(exc).__name__)
            _down_until = time.monotonic() + PAUSE
            return found
        if not scores:
            continue
        best = max(scores.values())
        if best - statistics.median(scores.values()) < DISTINCT:
            continue
        cutoff = max(MIN_SIMILARITY, best - MARGIN)
        for pk, similarity in sorted(scores.items(), key=lambda item: -item[1])[:PER_TERM]:
            if similarity < cutoff:
                break
            if similarity > found.get(pk, {}).get('similarity', 0):
                found[pk] = {'term': term, 'similarity': round(similarity, 3)}
    return found
