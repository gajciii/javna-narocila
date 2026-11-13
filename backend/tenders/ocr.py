"""OCR fallback for scanned PDFs: one page at a time, bounded by page count and wall time."""
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from django.conf import settings

log = logging.getLogger(__name__)
MIN_PAGE_TEXT = 20


def available():
    return settings.PIPELINE_OCR and all(shutil.which(tool) for tool in ('pdftoppm', 'tesseract'))


def needs_ocr(pages):
    """Scans: at least half the pages carry no text layer (text PDFs often have a few blank pages)."""
    blank = [p for p in pages if len(p.get('text', '').strip()) < MIN_PAGE_TEXT]
    return bool(pages) and len(blank) * 2 >= len(pages)


def ocr_page(path, number, workdir):
    image = Path(workdir) / f'page-{number}'
    subprocess.run(['pdftoppm', '-r', str(settings.PIPELINE_OCR_DPI), '-gray', '-png', '-singlefile',
                    '-f', str(number), '-l', str(number), str(path), str(image)],
                   check=True, capture_output=True, timeout=settings.PIPELINE_OCR_PAGE_TIMEOUT)
    png = image.with_suffix('.png')
    try:
        result = subprocess.run(['tesseract', str(png), 'stdout', '-l', settings.PIPELINE_OCR_LANGUAGES],
                                check=True, capture_output=True, timeout=settings.PIPELINE_OCR_PAGE_TIMEOUT,
                                env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
    finally:
        png.unlink(missing_ok=True)
    return result.stdout.decode('utf-8', 'replace').strip()


def apply_ocr(path, pages):
    """Fills blank pages in place; pages beyond the limits stay blank rather than failing the document."""
    if not available() or not needs_ocr(pages):
        return pages
    deadline = time.monotonic() + settings.PIPELINE_OCR_BUDGET
    blank = [p for p in pages if len(p.get('text', '').strip()) < MIN_PAGE_TEXT]
    with tempfile.TemporaryDirectory(prefix='ocr-') as workdir:
        for page in blank[:settings.PIPELINE_OCR_MAX_PAGES]:
            if time.monotonic() >= deadline:
                break
            try:
                text = ocr_page(path, page['page'], workdir)
            except (subprocess.SubprocessError, OSError) as exc:
                log.warning('OCR failed on page %s: %s', page['page'], type(exc).__name__)
                continue
            if len(text) >= MIN_PAGE_TEXT:
                page['text'] = text
                page['locator'] = f"stran {page['page']} (OCR)"
    return pages
