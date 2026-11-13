from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from .annual_reports import latest_report
from .validation import validate_profile


class AnnualReportTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    @patch.dict('os.environ', {'AJPES_LP_API_KEY': 'test-key', 'AJPES_LP_API_BASE': 'https://wwwa.ajpes.si'})
    @patch('tenders.annual_reports.requests.get')
    def test_uses_latest_structured_report_for_the_requested_company(self, get):
        def success(data):
            return Mock(status_code=200, json=Mock(return_value={'status': 'USPESNO', 'podatki': data}))

        get.side_effect = [success({'subjekt': {'maticnaStevilka': '0123456000'}, 'viri': [
            {'identifikatorVira': 'older', 'vrstalp': '01', 'leto': 2024},
            {'identifikatorVira': 'document', 'vrstalp': '04', 'leto': 2026},
            {'identifikatorVira': 'latest', 'vrstalp': '01', 'leto': 2025},
        ]}), success({'porocilo': {'maticnaStevilka': '0123456000', 'identifikatorVira': 'latest', 'leto': 2025,
                                  'postavke': {'T110': 0, 'T056': -12, 'T001': True, 'T188': 12.75}}})]
        result = latest_report('0123456')
        self.assertEqual(result['state'], 'available')
        self.assertEqual(result['report']['net_sales'], 0)
        self.assertEqual(result['report']['equity'], -12)
        self.assertIsNone(result['report']['assets'])
        self.assertEqual(result['report']['average_employees'], 12.75)
        self.assertEqual(get.call_args.kwargs['params']['identifikatorVira'], 'latest')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertEqual(latest_report('0123456000'), result)
        self.assertEqual(get.call_count, 2)

    @patch.dict('os.environ', {'AJPES_LP_API_KEY': 'test-key', 'AJPES_LP_API_BASE': 'https://wwwa.ajpes.si'})
    @patch('tenders.annual_reports.fetch')
    def test_rejects_report_for_another_company(self, fetch):
        fetch.side_effect = [{'subjekt': {'maticnaStevilka': '0123456000'}, 'viri': [
            {'identifikatorVira': 'latest', 'vrstalp': '01', 'leto': 2025},
        ]}, {'porocilo': {'maticnaStevilka': '0987654000', 'identifikatorVira': 'latest', 'leto': 2025,
                         'postavke': {'T110': 100}}}]
        self.assertEqual(latest_report('0123456')['state'], 'unavailable')

    def test_manual_employment_report_is_separate_from_available_staff_and_scoped_to_company(self):
        profile = {'name': 'Podjetje', 'registration_number': '0123456', 'staff_count': 3}
        report = {'average': 12.75, 'year': 2025}
        saved = validate_profile({'employment_report': report}, profile)
        self.assertEqual(saved['employment_report'], report)
        self.assertEqual(saved['staff_count'], 3)
        self.assertEqual(validate_profile({'registration_number': '0123456000'}, saved)['employment_report'], report)
        self.assertIsNone(validate_profile({'registration_number': '7654321', 'employment_report': report},
                                           saved)['employment_report'])
        with self.assertRaises(ValidationError):
            validate_profile({'employment_report': {'average': 10}}, profile)
