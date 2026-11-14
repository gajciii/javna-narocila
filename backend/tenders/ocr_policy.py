"""Offline OCR is searchable locally and never enters automatic embedding batches."""

OCR_IMPORT_PREFIX = 'ocr-local-'
OCR_IMPORT_VERSION = OCR_IMPORT_PREFIX + 'v1'


def preferred_ocr_content(digest):
    from .models import IndexedContent
    return (IndexedContent.objects.filter(sha256=digest, extractor_version=OCR_IMPORT_VERSION, format='pdf')
            .order_by('-created_at', 'pk').first())
