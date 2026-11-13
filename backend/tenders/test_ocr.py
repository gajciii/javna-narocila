import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from reportlab.pdfgen import canvas

from .deep_extract import extract_document
from .ocr import apply_ocr, needs_ocr

SCAN_TEXT = 'Ponudnik mora predložiti referenco za izvedbo del.'


def blank_pdf(path, pages):
    pdf = canvas.Canvas(str(path))
    for _ in range(pages):
        pdf.showPage()
    pdf.save()


@override_settings(PIPELINE_OCR=True, PIPELINE_OCR_MAX_PAGES=40, PIPELINE_OCR_BUDGET=240)
@patch('tenders.ocr.available', return_value=True)
class OcrTests(SimpleTestCase):
    def test_only_mostly_textless_documents_are_scans(self, _available):
        text = {'page': 1, 'text': SCAN_TEXT}
        blank = {'page': 2, 'text': ''}
        self.assertFalse(needs_ocr([text, text, blank]))
        self.assertTrue(needs_ocr([text, blank]))
        self.assertFalse(needs_ocr([]))

    def test_scanned_pdf_gets_ocr_text_with_marked_locator(self, _available):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sken.pdf'
            blank_pdf(path, 2)
            with patch('tenders.ocr.ocr_page', return_value=SCAN_TEXT) as ocr_page:
                pages, kind = extract_document(path, 'sken.pdf')
        self.assertEqual(kind, 'pdf')
        self.assertEqual([p['text'] for p in pages], [SCAN_TEXT, SCAN_TEXT])
        self.assertEqual(pages[0]['locator'], 'stran 1 (OCR)')
        self.assertEqual([c.args[1] for c in ocr_page.call_args_list], [1, 2])

    @override_settings(PIPELINE_OCR_MAX_PAGES=2)
    def test_page_limit_and_failed_pages_leave_the_rest_blank(self, _available):
        pages = [{'page': n, 'text': ''} for n in range(1, 5)]
        results = [subprocess.TimeoutExpired('tesseract', 60), SCAN_TEXT]
        with patch('tenders.ocr.ocr_page', side_effect=results) as ocr_page:
            apply_ocr('scan.pdf', pages)
        self.assertEqual(ocr_page.call_count, 2)
        self.assertEqual([p['text'] for p in pages], ['', SCAN_TEXT, '', ''])

    @override_settings(PIPELINE_OCR_BUDGET=0)
    def test_time_budget_stops_ocr(self, _available):
        pages = [{'page': 1, 'text': ''}]
        with patch('tenders.ocr.ocr_page') as ocr_page:
            apply_ocr('scan.pdf', pages)
        ocr_page.assert_not_called()

    def test_disabled_ocr_leaves_pages_untouched(self, available):
        available.return_value = False
        pages = [{'page': 1, 'text': ''}]
        with patch('tenders.ocr.ocr_page') as ocr_page:
            self.assertEqual(apply_ocr('scan.pdf', pages), [{'page': 1, 'text': ''}])
        ocr_page.assert_not_called()


class OcrSettingTests(SimpleTestCase):
    @override_settings(PIPELINE_OCR=False)
    def test_ocr_is_off_unless_enabled(self):
        from .ocr import available
        self.assertFalse(available())
