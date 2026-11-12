import hashlib
import json
import re
import math
from pathlib import Path
from django.conf import settings
from django.db import connection
from django.db.models import Func, IntegerField
from pypdf import PdfReader
from .models import Document, Tender


def normalized(text):
    return re.sub(r'\s+', ' ', str(text)).strip().casefold()


def extract_pages(path, max_bytes=10 * 1024 * 1024, max_pages=150):
    """PDF text extraction, preserving page numbers. Never invent OCR output."""
    if Path(path).stat().st_size > max_bytes:
        raise ValueError('Dokument presega omejitev velikosti.')
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError('Zaščitenih PDF-jev v prototipu ne obdelujemo.')
    if len(reader.pages) > max_pages:
        raise ValueError('Dokument presega omejitev strani za prototip.')
    pages = []
    for number, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents and len(contents.get_data()) > 12 * 1024 * 1024:
            raise ValueError('Stran je prevelika za obdelavo v prototipu.')
        pages.append({'page': number, 'text': page.extract_text() or ''})
    return pages


def evidence_valid(pages, page_number, quote):
    if not isinstance(page_number, int) or not quote or len(normalized(quote)) < 8:
        return False
    page = next((p for p in pages if p['page'] == page_number), None)
    return bool(page and normalized(quote) in normalized(page['text']))


def validated_extraction(data, document):
    allowed_kinds = {'reference_count', 'reference_value', 'staff', 'technology', 'certification'}
    requirements = []
    for item in data.get('requirements', []):
        if not isinstance(item, dict):
            continue
        if item.get('kind') not in allowed_kinds:
            continue
        if not evidence_valid(document.pages, item.get('page'), item.get('quote')):
            continue
        if not isinstance(item.get('title'), str) or not isinstance(item.get('id'), str):
            continue
        result = {**item, 'document_id': document.id}
        if item.get('kind') == 'certification':
            if not isinstance(item.get('certification'), str) or not item['certification'].strip() or len(item['certification']) > 150:
                continue
            if not isinstance(item.get('requires_manual_review', False), bool):
                continue
            from .matching import certification_key
            if certification_key(item['certification']) not in certification_key(item['quote']):
                continue
        elif item.get('kind') == 'technology':
            tech = item.get('technologies')
            if not isinstance(tech, list) or not tech or not all(isinstance(t, str) and t.strip() for t in tech):
                continue
        else:
            if isinstance(result.get('minimum'), bool) or not isinstance(result.get('minimum'), (int, float)) or not math.isfinite(result['minimum']) or result['minimum'] < 0:
                continue
        age = result.get('max_age_years')
        if age is not None and (isinstance(age, bool) or not isinstance(age, int) or not 0 <= age <= 100):
            continue
        requirements.append(result)
    return {'summary': str(data.get('summary', ''))[:10000], 'requirements': requirements,
            'criteria': [c for c in data.get('criteria', []) if isinstance(c, dict) and isinstance(c.get('title'), str) and isinstance(c.get('weight'), (int, float)) and 0 <= c['weight'] <= 100],
            'mode': data.get('mode', 'demo'), 'rejected_requirements': len(data.get('requirements', [])) - len(requirements)}


def load_demo_documents():
    root = settings.DEMO_DOCUMENTS_ROOT
    if not root.exists():
        return
    for sidecar in root.glob('*.json'):
        try:
            metadata = json.loads(sidecar.read_text(encoding='utf-8'))
            file_path = sidecar.with_suffix('.pdf')
            if not file_path.exists() or not Tender.objects.filter(pk=metadata['tender_id']).exists():
                continue
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            old = Document.objects.filter(pk=metadata['id']).first()
            if old and old.sha256 == digest and old.extraction:
                continue
            pages = extract_pages(file_path)
            readable = sum(len(p['text'].strip()) for p in pages) >= 50
            doc, _ = Document.objects.update_or_create(pk=metadata['id'], defaults={
                'tender_id': metadata['tender_id'], 'title': metadata['title'],
                'path': str(file_path.resolve()), 'version': metadata['version'],
                'pages': pages, 'sha256': digest, 'status': 'processed' if readable else 'unprocessed',
                'error': '' if readable else 'Manjka besedilna plast; potreben je OCR.'})
            doc.extraction = validated_extraction({**metadata, 'mode': 'demo'}, doc)
            doc.save(update_fields=['extraction'])
        except (KeyError, ValueError, OSError, json.JSONDecodeError):
            continue


def document_metadata():
    function = 'jsonb_array_length' if connection.vendor == 'postgresql' else 'json_array_length'
    return Document.objects.defer('pages').annotate(
        _page_count=Func('pages', function=function, output_field=IntegerField()))


def active_documents(tender, metadata_only=False):
    version = tender.data.get('version', 1)
    if metadata_only and hasattr(tender, '_document_metadata'):
        records = [doc for doc in tender._document_metadata if doc.version <= version]
    else:
        query = document_metadata().filter(tender=tender) if metadata_only else tender.document_records.all()
        records = list(query.filter(version__lte=version).order_by('id'))
    if not records:
        return []
    # Demo versions replace the same document family, while uploaded attachments remain additive.
    by_family = {}
    for doc in records:
        if doc.id.startswith(('pjn-doc-', 'index-doc-')) and doc.version != tender.data.get('version', 1):
            continue  # An older source PDF must not validate a corrected notice.
        family = re.sub(r'-v\d+$', '', doc.id)
        if family not in by_family or doc.version > by_family[family].version:
            by_family[family] = doc
    return list(by_family.values())


def serialize_document(doc):
    page_count = doc._page_count if hasattr(doc, '_page_count') else len(doc.pages)
    return {'id': doc.id, 'title': doc.title, 'url': f'/api/documents/{doc.id}', 'pages': page_count,
            'status': doc.status, 'version': doc.version, 'error': doc.error,
            'analysis_mode': doc.extraction.get('mode', 'unprocessed')}
