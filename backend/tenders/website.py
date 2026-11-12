"""Suggest profile fields from a company's own public website.

The site is read as untrusted data. Nothing is saved here: the endpoint returns
suggestions with a verbatim quote and page URL for each, and the user chooses
what to copy into the profile form. Without an AI key a transparent keyword
heuristic is used; with a key, AI output is accepted only when its quotes are
found in the fetched text.
"""
import ipaddress
import logging
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from .matching import text_normalize

log = logging.getLogger(__name__)

MAX_PAGE_BYTES = 1_500_000
MAX_PAGES = 8
MAX_TEXT_PER_PAGE = 20_000
TIME_BUDGET = 25
USER_AGENT = 'RazpIzi/0.4 (predizpolnitev profila; enkraten ogled)'

# Subpages that usually describe what a company does.
PRIORITY_PATHS = ['storitv', 'service', 'o-nas', 'onas', 'about', 'referenc', 'projekt', 'portfolio', 'resitv',
                  'solution', 'dejavnost', 'produkt', 'product', 'kaj-delamo', 'podjetje', 'company', 'spletn',
                  'aplikacij', 'razvoj', 'svetovanj', 'izdelk']
SKIP_PATHS = ['pogoji', 'piskot', 'cookie', 'zasebnost', 'privacy', 'varstvo', 'pravna', 'legal', 'login', 'prijava',
              'kosaric', 'cart', 'kontakt', 'contact', 'checkout', 'wp-admin', 'wp-login', 'feed', 'sitemap', 'tag/', 'author/', 'blog', 'novic', 'news', 'clanek', 'article']
ASSET_EXT = re.compile(r'\.(?:jpe?g|png|gif|svg|webp|ico|pdf|zip|docx?|xlsx?|pptx?|mp4|mp3|css|js|xml|json|woff2?)$', re.I)

# (label shown in profile, keywords added to profile, normalized search terms)
EXPERTISE = [
    ('Izdelava spletnih strani', ['spletne strani'], ['spletne strani', 'spletnih strani', 'spletno stran', 'izdelava spletn', 'website', 'web design', 'spletna predstavitev']),
    ('Razvoj spletnih aplikacij', ['spletne aplikacije'], ['spletne aplikacij', 'spletnih aplikacij', 'spletno aplikacij', 'web application', 'web app', 'spletne platform', 'spletnih platform']),
    ('Spletne trgovine in e-poslovanje', ['spletne trgovine', 'e-trgovina'], ['spletne trgovin', 'spletnih trgovin', 'spletno trgovin', 'e-trgovin', 'e-commerce', 'ecommerce', 'woocommerce', 'shopify']),
    ('Mobilne aplikacije', ['mobilne aplikacije'], ['mobilne aplikacij', 'mobilnih aplikacij', 'mobile app', 'ios in android', 'android in ios']),
    ('Programska oprema po meri', ['programska oprema'], ['programska oprema', 'programske opreme', 'programsko opremo', 'razvoj programsk', 'software development', 'custom software', 'informacijski sistem', 'informacijskih sistem']),
    ('SEO in digitalni marketing', ['SEO', 'digitalni marketing'], ['seo', 'optimizacija za iskalnik', 'digitalni marketing', 'digitalnega marketinga', 'spletno oglasevanj', 'google ads', 'oglasevanj', 'druzbena omrezja']),
    ('Gostovanje in vzdrževanje spletnih strani', ['gostovanje', 'vzdrževanje'], ['gostovanj', 'hosting', 'registracij domen', 'domene', 'vzdrzevanj']),
    ('IT svetovanje in digitalizacija', ['digitalizacija', 'svetovanje'], ['svetovanj', 'digitalizacij', 'consulting', 'digitalna preobrazb']),
    ('Grafično oblikovanje in UX/UI', ['oblikovanje', 'UX/UI'], ['graficno oblikovanj', 'celostna graficna', 'ux/ui', 'uporabniska izkusnj', 'user experience']),
    ('Oblak in sistemska administracija', ['oblak', 'sistemska administracija'], ['oblacn', 'cloud', 'sistemsk administracij', 'devops']),
    ('Podatkovna analitika in umetna inteligenca', ['analitika', 'umetna inteligenca'], ['podatkovn analitik', 'analitika podatkov', 'umetna inteligenca', 'umetne inteligence', 'strojno ucenj', 'machine learning', 'business intelligence']),
    ('IoT in avtomatizacija', ['IoT', 'avtomatizacija'], ['iot', 'internet stvari', 'senzor', 'avtomatizacij', 'krmiljenj']),
    ('Kibernetska varnost', ['kibernetska varnost'], ['kibernetsk', 'informacijska varnost', 'cybersecurity', 'penetracijsk']),
    ('Izobraževanja in usposabljanja', ['izobraževanja'], ['izobrazevanj', 'usposabljanj', 'delavnic', 'tecaj']),
    ('Gradbeništvo', ['gradnja'], ['gradben', 'gradnj', 'rekonstrukcij', 'sanacij']),
    ('Energetika', ['energetika'], ['energetsk', 'soncne elektrarn', 'fotovoltai', 'toplotne crpalk', 'energijsk ucinkovit']),
]

TECHNOLOGIES = ['WordPress', 'WooCommerce', 'Shopify', 'PrestaShop', 'Magento', 'Drupal', 'Joomla', 'React', 'React Native',
                'Next.js', 'Vue.js', 'Nuxt.js', 'Angular', 'Svelte', 'Node.js', 'TypeScript', 'JavaScript', 'Django', 'Python',
                'PHP', 'Laravel', 'Symfony', 'ASP.NET', '.NET', 'Java', 'Spring', 'Flutter', 'Swift', 'Kotlin', 'Docker',
                'Kubernetes', 'AWS', 'Azure', 'Google Cloud', 'PostgreSQL', 'MySQL', 'MongoDB', 'Firebase', 'Tailwind',
                'Figma', 'Odoo', 'SAP', 'Moodle', 'Elementor', 'Webflow', 'Stripe', 'GraphQL']
# Markers in the page source. These only show how the website itself is built.
CODE_SIGNATURES = [('Next.js', ['/_next/static/']), ('Nuxt.js', ['/_nuxt/', 'window.__nuxt']), ('WordPress', ['/wp-content/', '/wp-includes/']),
                   ('WooCommerce', ['woocommerce']), ('Shopify', ['cdn.shopify.com']), ('Elementor', ['elementor-']),
                   ('Webflow', ['webflow.js', 'data-wf-page']), ('Wix', ['static.wixstatic.com']), ('Drupal', ['/sites/default/files/', 'drupal-settings-json']),
                   ('Joomla', ['/media/jui/', 'joomla']), ('PrestaShop', ['prestashop'])]


class WebsiteUnavailable(Exception):
    pass


def normalize_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError('Vnesite naslov spletne strani, na primer https://podjetje.si.')
    value = value.strip()
    if not re.match(r'^[a-z][a-z0-9+.-]*://', value, re.I):
        value = 'https://' + value
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Podprti so samo javni naslovi http(s) brez uporabniškega imena.')
    if parts.port not in (None, 80, 443):
        raise ValueError('Spletna stran mora uporabljati standardna vrata.')
    host = parts.hostname.lower().rstrip('.')
    if '.' not in host:
        raise ValueError('Vnesite polno domeno, na primer podjetje.si.')
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or '/', parts.query, ''))


def assert_public_host(host):
    """Refuse loopback/private/link-local targets so the server cannot be used to probe internal networks."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebsiteUnavailable('Domene ni mogoče najti. Preverite naslov.') from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split('%')[0])
        if not address.is_global:
            raise ValueError('Naslov ne kaže na javno spletno stran.')


def site_key(host):
    host = (host or '').lower()
    return host[4:] if host.startswith('www.') else host


def fetch(url, deadline):
    """GET one HTML page with manual, re-validated redirects and a size limit."""
    for _ in range(4):
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or parts.port not in (None, 80, 443):
            raise WebsiteUnavailable('Preusmeritev vodi na nepodprt naslov.')
        assert_public_host(parts.hostname)
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise WebsiteUnavailable('Časovna omejitev branja je presežena.')
        try:
            with requests.get(url, timeout=(5, min(10, remaining)), stream=True, allow_redirects=False,
                              headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml'}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get('Location', ''))
                    continue
                if response.status_code != 200:
                    raise WebsiteUnavailable(f'Stran je vrnila HTTP {response.status_code}.')
                if 'html' not in response.headers.get('Content-Type', 'text/html').lower():
                    raise WebsiteUnavailable('Naslov ne vrača HTML strani.')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        raise WebsiteUnavailable('Stran presega omejitev velikosti.')
                    chunks.append(chunk)
                encoding = response.encoding if response.encoding and response.encoding.lower() != 'iso-8859-1' else 'utf-8'
                return url, b''.join(chunks).decode(encoding, errors='replace')
        except requests.RequestException as exc:
            raise WebsiteUnavailable('Spletne strani ni bilo mogoče prebrati.') from exc
    raise WebsiteUnavailable('Preveč preusmeritev.')


BLOCK_TAGS = {'p', 'div', 'section', 'article', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'tr', 'td', 'header',
              'footer', 'main', 'nav', 'blockquote', 'figcaption', 'dd', 'dt', 'a', 'button', 'label', 'option'}
SKIP_TAGS = {'script', 'style', 'svg', 'noscript', 'template', 'iframe', 'canvas'}


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.links, self.current = [], [], []
        self.title, self.meta, self.skip, self.in_title = '', {}, 0, False

    def flush(self):
        text = re.sub(r'\s+', ' ', ''.join(self.current)).strip()
        if text:
            self.blocks.append(text)
        self.current = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag == 'title':
            self.in_title = True
        elif tag == 'meta':
            key = (attrs.get('name') or attrs.get('property') or '').lower()
            if key in ('description', 'og:description', 'generator', 'keywords') and attrs.get('content'):
                self.meta[key] = attrs['content'].strip()
        elif tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag in BLOCK_TAGS:
            self.flush()

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag == 'title':
            self.in_title = False
        if tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title += data
        else:
            self.current.append(data)


def parse(url, html):
    parser = PageParser()
    parser.feed(html)
    parser.close()
    parser.flush()
    # Drop very short UI fragments and repeated navigation/testimonial blocks later by dedupe.
    blocks, size = [], 0
    for block in parser.blocks:
        if len(block) < 3 or size > MAX_TEXT_PER_PAGE:
            continue
        blocks.append(block[:2000])
        size += len(block)
    lowered = html.lower()
    detected = [name for name, markers in CODE_SIGNATURES if any(m in lowered for m in markers)]
    generator = parser.meta.get('generator', '')
    return {'url': url, 'title': re.sub(r'\s+', ' ', parser.title).strip()[:200], 'meta': parser.meta,
            'blocks': blocks, 'links': parser.links, 'code_technologies': detected, 'generator': generator[:120]}


def candidate_links(page, host):
    seen, scored = set(), []
    for href in page['links']:
        absolute = urljoin(page['url'], href.strip())
        parts = urlsplit(absolute)
        if parts.scheme not in ('http', 'https') or site_key(parts.hostname) != host:
            continue
        path = parts.path or '/'
        clean = urlunsplit((parts.scheme, parts.netloc.lower(), path, '', ''))
        low = text_normalize(path)
        if path in ('', '/') or clean in seen or ASSET_EXT.search(path) or any(s in low for s in SKIP_PATHS) or '/_next/' in path:
            continue
        seen.add(clean)
        priority = sum(term in low for term in PRIORITY_PATHS)
        depth = path.strip('/').count('/')
        # Prefer short service/about pages over deep blog posts.
        scored.append((-(priority * 3) + depth * 2, clean))
    return [url for _, url in sorted(scored)]


def crawl(url):
    deadline = time.monotonic() + TIME_BUDGET
    final_url, html = fetch(url, deadline)
    home = parse(final_url, html)
    pages, errors = [home], []
    host = site_key(urlsplit(final_url).hostname)
    for link in candidate_links(home, host)[:MAX_PAGES - 1]:
        if time.monotonic() > deadline - 2:
            errors.append('Časovna omejitev: prebrane niso vse podstrani.')
            break
        try:
            page_url, page_html = fetch(link, deadline)
            if site_key(urlsplit(page_url).hostname) == host:
                pages.append(parse(page_url, page_html))
        except (WebsiteUnavailable, ValueError):
            errors.append(f'Podstrani {link} ni bilo mogoče prebrati.')
    return final_url, pages, errors


SENTENCE = re.compile(r'(?<=[.!?])\s+')
INTRO = re.compile(r'\b(smo|nudimo|ponujamo|razvijamo|izdelujemo|izdelamo|zagotavljamo|specializirani|ukvarjamo|pomagamo|povečamo|we|our)\b', re.I)
# Customer quotes describe outcomes, not the company's own claims.
TESTIMONIAL = re.compile(r'^\s*["“„«]')
# 'Price does not include SEO' must not suggest SEO as a service.
NEGATION = re.compile(r'(?<![a-z])(ne vkljucuje|ni vkljucen|niso vkljucen|ne nudimo|ne ponujamo|brez)(?![a-z])')


def sentences(pages):
    """Unique text snippets with their page URL; repeated header/footer text is kept once."""
    seen, result = set(), []
    for page in pages:
        for block in page['blocks']:
            for sentence in SENTENCE.split(block):
                sentence = sentence.strip()
                key = text_normalize(sentence)
                if len(sentence) < 4 or key in seen:
                    continue
                seen.add(key)
                result.append({'url': page['url'], 'text': sentence[:400], 'norm': ' ' + key + ' '})
    return result


def term_pattern(term):
    return re.compile(r'(?<![a-z0-9])' + re.escape(term))


def heuristic(pages):
    snippets = sentences(pages)
    expertise, keywords = [], []
    for label, tags, terms in EXPERTISE:
        patterns = [term_pattern(term) for term in terms]
        hits = [s for s in snippets if any(p.search(s['norm']) for p in patterns) and not NEGATION.search(s['norm']) and not TESTIMONIAL.match(s['text'])]
        if hits:
            # Menu/footer items count little; explanatory sentences and a dedicated subpage count more.
            dedicated = any(any(p.search(' ' + text_normalize(urlsplit(page['url']).path.replace('-', ' ')) + ' ') for p in patterns) for page in pages[1:])
            score = sum(0.5 if len(s['text']) < 60 else 2 for s in hits) + (4 if dedicated else 0)
            hits.sort(key=lambda s: (not INTRO.search(s['text']), -min(len(s['text']), 200)))
            expertise.append({'value': label, 'count': score, 'tags': tags,
                              'evidence': [{'url': s['url'], 'quote': s['text'], 'kind': 'text'} for s in hits[:2]]})
    expertise.sort(key=lambda item: -item['count'])
    for item in expertise:
        keywords += [{'value': tag, 'evidence': item['evidence'][:1]} for tag in item.pop('tags')]
        item.pop('count')

    technologies, seen_tech = [], set()
    for name in TECHNOLOGIES:
        pattern = re.compile(r'(?<![A-Za-z0-9])' + re.escape(name) + r'(?![A-Za-z0-9])', re.I)
        hit = next((s for s in snippets if pattern.search(s['text']) and not TESTIMONIAL.match(s['text'])), None)
        if hit and name.lower() not in seen_tech:
            seen_tech.add(name.lower())
            technologies.append({'value': name, 'evidence': [{'url': hit['url'], 'quote': hit['text'], 'kind': 'text'}]})
    for page in pages[:1]:
        for name in page['code_technologies']:
            if name.lower() not in seen_tech:
                seen_tech.add(name.lower())
                technologies.append({'value': name, 'evidence': [{'url': page['url'], 'quote': f'{name} zaznan v izvorni kodi spletne strani podjetja.', 'kind': 'code'}]})

    description = None
    home = pages[0]
    meta = home['meta'].get('description') or home['meta'].get('og:description') or ''
    paragraphs = [b for page in pages[:3] for b in page['blocks'] if 120 <= len(b) <= 1200 and INTRO.search(b)]
    if paragraphs:
        text = paragraphs[0]
        description = {'value': text, 'evidence': [{'url': next(p['url'] for p in pages if text in p['blocks']), 'quote': text[:400], 'kind': 'text'}]}
    elif len(meta) >= 60:
        description = {'value': meta, 'evidence': [{'url': home['url'], 'quote': meta[:400], 'kind': 'meta'}]}

    activity = None
    if expertise:
        labels = [item['value'] for item in expertise[:3]]
        labels = [labels[0]] + [label[0].lower() + label[1:] if not label[:3].isupper() else label for label in labels[1:]]
        text = labels[0] if len(labels) == 1 else ', '.join(labels[:-1]) + ' in ' + labels[-1]
        activity = {'value': text, 'evidence': [e for item in expertise[:3] for e in item['evidence'][:1]]}
    return {'activity': activity, 'description': description, 'expertise': expertise,
            'technologies': technologies, 'keywords': list({k['value']: k for k in keywords}.values())}


EVIDENCE_SCHEMA = {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
    'properties': {'url': {'type': 'string'}, 'quote': {'type': 'string'}}, 'required': ['url', 'quote']}}
ITEM_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'properties': {'value': {'type': 'string'}, 'evidence': EVIDENCE_SCHEMA}, 'required': ['value', 'evidence']}
AI_SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'activity': ITEM_SCHEMA, 'description': ITEM_SCHEMA,
    'expertise': {'type': 'array', 'items': ITEM_SCHEMA}, 'technologies': {'type': 'array', 'items': ITEM_SCHEMA},
    'keywords': {'type': 'array', 'items': ITEM_SCHEMA},
}, 'required': ['activity', 'description', 'expertise', 'technologies', 'keywords']}


def squash(value):
    return re.sub(r'\s+', ' ', value).strip()


def grounded(item, page_text):
    evidence = []
    for e in item.get('evidence', [])[:3]:
        text = page_text.get(e.get('url'))
        quote = squash(e.get('quote', ''))
        if text and len(quote) >= 8 and quote in text:
            evidence.append({'url': e['url'], 'quote': quote[:400], 'kind': 'text'})
    value = squash(item.get('value', ''))
    return {'value': value[:1200], 'evidence': evidence} if value and evidence else None


def ai_suggestions(pages):
    from .ai import ai_enabled, structured_call
    if not ai_enabled():
        return None
    page_text = {p['url']: squash(' '.join(p['blocks'])) for p in pages}
    try:
        data = structured_call(AI_SCHEMA,
            'Iz besedila spletne strani podjetja pripravi predlog profila za iskanje javnih naročil. Piši slovensko. '
            'activity: ena vrstica o glavni dejavnosti. description: 2–4 stavki, kaj podjetje dela in za koga. '
            'expertise: do 8 strokovnih področij. technologies: samo izrecno omenjene tehnologije/platforme. keywords: do 10 kratkih iskalnih izrazov. '
            'Vsak predlog mora imeti vsaj en dobesedni citat (5–30 besed) iz besedila in URL strani, kjer je. '
            'Ne sklepaj o referencah, kadrih, prihodkih ali certifikatih. Mnenja strank niso dokaz o sposobnostih.',
            {'pages': [{'url': p['url'], 'title': p['title'], 'text': page_text[p['url']][:12000]} for p in pages]})
    except Exception as exc:
        log.warning('AI website analysis unavailable: %s', type(exc).__name__)
        return None
    result = {key: grounded(data[key], page_text) for key in ('activity', 'description')}
    for key in ('expertise', 'technologies', 'keywords'):
        result[key] = [g for g in (grounded(item, page_text) for item in data[key][:12]) if g]
    if not result['activity'] and not result['expertise']:
        return None
    return result


def analyze(url):
    start = normalize_url(url)
    final_url, pages, errors = crawl(start)
    words = sum(len(b.split()) for p in pages for b in p['blocks'])
    if words < 40:
        raise WebsiteUnavailable('Na strani je premalo berljivega besedila (morda se vsebina naloži šele z JavaScriptom). Profil dopolnite ročno.')
    suggestions, mode = ai_suggestions(pages), 'live'
    if suggestions is None:
        suggestions, mode = heuristic(pages), 'heuristic'
    # Technologies detected in page source are useful but weaker evidence; always keep them after AI ones.
    if mode == 'live':
        names = {t['value'].lower() for t in suggestions['technologies']}
        suggestions['technologies'] += [t for t in heuristic(pages)['technologies'] if t['evidence'][0]['kind'] == 'code' and t['value'].lower() not in names]
    found = sum(bool(suggestions[k]) for k in ('activity', 'description')) + sum(len(suggestions[k]) for k in ('expertise', 'technologies', 'keywords'))
    return {
        'url': start, 'final_url': final_url, 'mode': mode,
        'pages': [{'url': p['url'], 'title': p['title']} for p in pages],
        'suggestions': suggestions,
        'warning': ' '.join(dict.fromkeys(errors)) or None,
        'message': (('AI predlog s preverjenimi citati' if mode == 'live' else 'Predlog po ključnih besedah s spletne strani')
                    + f' · prebranih strani: {len(pages)}. Izberite, kaj prenesete v obrazec; shrani se šele s potrditvijo profila.')
                   if found else 'Na strani nismo prepoznali dejavnosti. Profil dopolnite ročno.',
    }
