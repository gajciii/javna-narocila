from django.test import SimpleTestCase

from tenders.pjn_transport import submission_url


class SubmissionUrlTests(SimpleTestCase):
    def test_keeps_https_ejn_link(self):
        url = 'https://ejn.gov.si/ponudba/pages/aktualno/aktualno_jnc_podrobno.xhtml?zadevaId=81724'
        self.assertEqual(submission_url(url), url)

    def test_rejects_unsafe_values(self):
        for value in (None, '', 'javascript:alert(1)', 'http://ejn.gov.si/x', 'https://user:pw@ejn.gov.si/x', 42):
            self.assertIsNone(submission_url(value))
