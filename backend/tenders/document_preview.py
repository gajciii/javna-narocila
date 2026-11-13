"""Read-only preview of indexed text, independent of original-file storage."""
import re
import secrets
from html import escape

from django.http import HttpResponse


def preview(document, request, *, original_missing=False):
    pages = document.indexed_content.pages if document.indexed_content_id else document.pages
    pages = [page for page in pages if isinstance(page, dict) and page.get('text', '').strip()]
    if not pages:
        return HttpResponse('Besedilo dokumenta še ni na voljo.', status=404, content_type='text/plain; charset=utf-8')
    query = request.GET.get('q', '').strip()[:200]
    pattern = re.compile(re.escape(query), re.IGNORECASE) if query else None
    matches = 0
    sections = []
    for index, page in enumerate(pages, 1):
        text = str(page['text'])
        parts = []
        start = 0
        if pattern:
            for match in pattern.finditer(text):
                parts.extend((escape(text[start:match.start()]), '<mark>', escape(match.group()), '</mark>'))
                start = match.end()
                matches += 1
        parts.append(escape(text[start:]))
        label = page.get('locator') or f"Stran oziroma del {page.get('page', index)}"
        page_id = escape(str(page.get('page', index)), quote=True)
        sections.append(f'<section id="page-{page_id}"><h2>{escape(str(label))}</h2><div class="text">{"".join(parts)}</div></section>')
    nonce = secrets.token_urlsafe(24)
    base = f'/api/documents/{document.pk}'
    notice = ('Izvirna datoteka ni na voljo v lokalni shrambi. Prikazano je shranjeno izluščeno besedilo.'
              if original_missing else 'Prikazano je izluščeno besedilo. Oblikovanje in številčenje delov se lahko razlikujeta od izvirnika.')
    html = f'''<!doctype html><html lang="sl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(document.title)} · RazpIzi</title><style nonce="{nonce}">
*{{box-sizing:border-box}}body{{margin:0;background:#f3f3ef;color:#202d33;font:18px/1.65 system-ui,sans-serif}}header,main{{max-width:1080px;margin:auto;padding:32px}}header{{background:white;border-bottom:3px solid #417186}}h1{{font-size:28px;line-height:1.3;overflow-wrap:anywhere}}h2{{font-size:17px;color:#417186}}p{{margin:12px 0}}a{{color:#417186}}nav{{display:flex;flex-wrap:wrap;gap:24px}}form{{display:flex;gap:12px;margin-top:24px}}input{{min-width:0;flex:1;padding:12px;border:1px solid #d5d9d3;font:inherit}}button{{background:#417186;color:white;border:0;padding:12px 20px;font:inherit;cursor:pointer}}section{{padding:16px 0 36px;border-bottom:1px solid #d5d9d3;scroll-margin-top:20px}}.text{{white-space:pre-wrap;overflow-wrap:anywhere}}mark{{background:#ffdd8b;color:#17282f}}.notice{{color:#52616a;font-size:15px}}
</style></head><body><header><nav><a href="/#/razpisi/{escape(document.tender_id, quote=True)}">← Nazaj na razpis</a><a href="{base}?download=1">Odpri izvirno datoteko</a></nav><h1>{escape(document.title)}</h1><p class="notice">{notice}</p><form action="{base}/text" method="get"><input name="q" aria-label="Išči v besedilu" placeholder="Išči v besedilu dokumenta" value="{escape(query, quote=True)}" maxlength="200"><button>Išči</button></form>{f'<p>{matches} zadetkov za »{escape(query)}«</p>' if query else ''}</header><main>{''.join(sections)}</main>
<script nonce="{nonce}">
const params=new URLSearchParams(location.hash.slice(1));
if(params.has('search')){{const target=new URL(location.href);target.searchParams.set('q',params.get('search'));target.hash=params.has('page')?'page-'+params.get('page'):'';location.replace(target.href);}}
else if(params.has('page')){{document.getElementById('page-'+params.get('page'))?.scrollIntoView();}}
else if(!location.hash){{document.querySelector('mark')?.scrollIntoView({{block:'center'}});}}
</script></body></html>'''
    response = HttpResponse(html, content_type='text/html; charset=utf-8')
    response['Content-Security-Policy'] = f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; form-action 'self'; base-uri 'none'; frame-ancestors 'self'"
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response
