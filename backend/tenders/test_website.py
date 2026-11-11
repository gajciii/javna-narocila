from unittest.mock import patch

from django.test import TestCase

from .seed import ensure_seed, get_profile
from .website import WebsiteUnavailable, assert_public_host, grounded, normalize_url

HOME = '''<html><head><title>Primer d.o.o.</title><meta name="description" content="Kratko.">
<script src="/_next/static/chunks/main.js"></script></head><body>
<nav><a href="/storitve/spletne-trgovine">Spletne trgovine</a><a href="/pogoji">Pogoji</a><a href="/blog/seo">Blog</a>
<a href="https://drugje.si/x">Zunanje</a><a href="/slika.png">Slika</a></nav>
<p>Specializirani smo za razvoj spletnih aplikacij in informacijskih sistemov za javni sektor, ki jih gradimo z orodji React in Django.</p>
<p>Cena ne vključuje SEO optimizacije in oglaševanja na družbenih omrežjih.</p>
<p>“Odlično delo pri spletni strani in SEO, priporočamo jih vsem.”</p>
<p>Nudimo tudi vzdrževanje in gostovanje aplikacij na varni infrastrukturi za naše dolgoletne stranke.</p>
</body></html>'''
SHOP = '<html><head><title>Trgovine</title></head><body><p>Izdelamo spletne trgovine na platformi WooCommerce za mala podjetja.</p></body></html>'


def fake_fetch(url, deadline):
    pages = {'https://primer.si/': HOME, 'https://primer.si/storitve/spletne-trgovine': SHOP}
    if url not in pages:
        raise WebsiteUnavailable('ni')
    return url, pages[url]


class WebsiteProfileTests(TestCase):
    def setUp(self):
        ensure_seed()
        self.fetch = self.enterContext(patch('tenders.website.fetch', side_effect=fake_fetch))
        self.enterContext(patch.dict('os.environ', {'OPENAI_API_KEY': '', 'OPENROUTER_API_KEY': ''}))

    def post(self, url):
        return self.client.post('/api/profile/website', {'url': url}, content_type='application/json')

    def test_suggestions_are_grounded_and_do_not_change_profile(self):
        before = get_profile()
        response = self.post('primer.si')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['mode'], 'heuristic')
        self.assertEqual(data['url'], 'https://primer.si/')
        crawled = [p['url'] for p in data['pages']]
        self.assertEqual(crawled, ['https://primer.si/', 'https://primer.si/storitve/spletne-trgovine'])
        s = data['suggestions']
        expertise = [e['value'] for e in s['expertise']]
        self.assertIn('Razvoj spletnih aplikacij', expertise)
        self.assertIn('Spletne trgovine in e-poslovanje', expertise)
        # A negated sentence and a customer testimonial are not evidence of SEO services.
        self.assertNotIn('SEO in digitalni marketing', expertise)
        techs = {t['value']: t['evidence'][0]['kind'] for t in s['technologies']}
        self.assertEqual(techs['React'], 'text')
        self.assertEqual(techs['WooCommerce'], 'text')
        self.assertEqual(techs['Next.js'], 'code')
        self.assertTrue(s['description']['value'].startswith('Specializirani smo'))
        for item in s['expertise'] + s['technologies'] + s['keywords']:
            self.assertTrue(item['evidence'] and item['evidence'][0]['url'].startswith('https://primer.si/'))
        self.assertEqual(get_profile(), before)

    def test_invalid_and_internal_urls_are_rejected(self):
        for value in ['', 'ftp://primer.si', 'http://localhost', 'https://user:pw@primer.si', 'https://primer.si:8080']:
            self.assertEqual(self.post(value).status_code, 400, value)
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('10.0.0.5', 0))]):
            with self.assertRaises(ValueError):
                assert_public_host('intranet.example')
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('169.254.169.254', 0))]):
            with self.assertRaises(ValueError):
                assert_public_host('metadata.example')

    def test_unreachable_site_returns_502(self):
        self.fetch.side_effect = WebsiteUnavailable('Spletne strani ni bilo mogoče prebrati.')
        response = self.post('https://primer.si')
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['code'], 'website_unavailable')

    def test_ai_items_without_verbatim_quote_are_dropped(self):
        text = {'https://primer.si/': 'Specializirani smo za razvoj spletnih aplikacij.'}
        self.assertIsNone(grounded({'value': 'Gradnja mostov', 'evidence': [{'url': 'https://primer.si/', 'quote': 'gradimo mostove po vsej Evropi'}]}, text))
        self.assertIsNone(grounded({'value': 'Aplikacije', 'evidence': [{'url': 'https://drugje.si/', 'quote': 'razvoj spletnih aplikacij'}]}, text))
        self.assertEqual(grounded({'value': 'Aplikacije', 'evidence': [{'url': 'https://primer.si/', 'quote': 'razvoj  spletnih aplikacij'}]}, text)['evidence'][0]['quote'], 'razvoj spletnih aplikacij')

    def test_normalize_url(self):
        self.assertEqual(normalize_url(' Primer.si/o-nas#top '), 'https://primer.si/o-nas')
