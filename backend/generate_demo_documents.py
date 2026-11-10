"""Reproducible, clearly fictional tender documents and extraction fixtures.

Run with the project virtualenv. PDFs deliberately contain selectable Slovenian
text; sidecars describe expected extraction, not facts about an actual tender.
"""
from pathlib import Path
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle


OUT = Path(__file__).parent / "demo_documents"
YEAR = datetime.now(ZoneInfo("Europe/Ljubljana")).year


def fonts():
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    for regular, bold in candidates:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("Radar", regular))
            pdfmetrics.registerFont(TTFont("RadarBold", bold))
            return
    raise RuntimeError("Install DejaVu Sans fonts to generate Slovenian PDF documents.")


def req(id, title, kind, domain=None, minimum=None, page=2, quote="", **extra):
    result = dict(id=id, title=title, kind=kind, page=page, quote=quote)
    if domain is not None:
        result["domain"] = domain
    if minimum is not None:
        result["minimum"] = minimum
    result.update(extra)
    return result


def documents():
    common = "To je izmišljen razpis za predstavitev prototipa Razpisni radar. Ne gre za dejansko javno naročilo. Vsi pogoji in vrednosti so demonstracijski."
    energy_requirements = [
        req("energy-reference", "Najmanj ena primerljiva energetska referenca", "reference_count", "energy", 1, max_age_years=3, quote="Ponudnik mora izkazati najmanj eno zaključeno referenco na področju energetskega spremljanja v zadnjih treh letih."),
        req("energy-value", "Vrednost primerljive reference najmanj 80.000 EUR", "reference_value", "energy", 80000, max_age_years=3, quote="Vrednost najmanj ene primerljive zaključene reference mora znašati vsaj 80.000 EUR brez DDV."),
        req("energy-staff", "Ekipa najmanj treh strokovnjakov", "staff", minimum=3, quote="Ponudnik mora zagotoviti projektno ekipo najmanj treh strokovnjakov."),
    ]
    sport_requirements = [
        req("sport-reference", "Zaključena primerljiva športna referenca", "reference_count", "sport", 1, max_age_years=3, quote="Ponudnik mora izkazati najmanj eno zaključeno referenco razvoja spletne platforme za športna tekmovanja v zadnjih treh letih."),
        req("sport-value", "Športna referenca v vrednosti vsaj 60.000 EUR", "reference_value", "sport", 60000, max_age_years=3, quote="Primerljiva referenca mora imeti vrednost najmanj 60.000 EUR brez DDV; dokazilo mora vsebovati vrednost in datum zaključka."),
    ]
    output = [
        dict(id="energy-v1", tender_id="energy-iot", version=1, title="IoT platforma za spremljanje porabe energije", summary="Razvoj spletne platforme za zbiranje podatkov senzorjev, prikaz porabe energije in avtomatska opozorila v javnih stavbah.", requirements=energy_requirements, criteria=[{"title":"Ponudbena cena", "weight":60},{"title":"Tehnična kakovost rešitve", "weight":30},{"title":"Načrt podpore", "weight":10}],
             scope="Predmet je razvoj programske platforme po meri za spremljanje porabe električne energije, vode in toplote. Rešitev vključuje integracijo obstoječih IoT senzorjev, zajem podatkov prek MQTT, REST API, spletno nadzorno ploščo in opozorila. Sama dobava merilnikov ni predmet naročila.",
             delivery="Predvidena izvedba traja šest mesecev. Ponudnik pripravi analizo, prototip, produkcijsko rešitev, dokumentacijo API in usposabljanje. Podprta morata biti izvoz podatkov in pregled sprememb."),
        dict(id="sport-v1", tender_id="sport-portal", version=1, title="Spletni portal za upravljanje športnih tekmovanj", summary="Spletna platforma za prijavo tekmovalcev, urnike, rezultate v živo in integracijo merilnih sistemov.", requirements=sport_requirements, criteria=[{"title":"Ponudbena cena", "weight":70},{"title":"Uporabniška izkušnja in načrt izvedbe", "weight":30}],
             scope="Naročnik potrebuje razvoj spletne aplikacije za organizacijo športnih tekmovanj. Rešitev vključuje prijave tekmovalcev, upravljanje kategorij, rezultate v realnem času, mobilno prilagoditev in povezovanje merilne opreme prek API. Administracija mora omogočati vloge organizatorja, sodnika in urednika.",
             delivery="Predvidena izvedba traja štiri mesece. Obvezna sta uvoz obstoječih rezultatov in preizkus na demonstracijskem tekmovanju. Datum in vrednost primerljive reference sta potrebna za presojo referenčnega pogoja."),
    ]
    for version, count in [(1,1),(2,2)]:
        text = "Ponudnik mora izkazati najmanj eno zaključeno referenco analize satelitskih posnetkov v zadnjih treh letih." if version == 1 else "Ponudnik mora izkazati najmanj dve zaključeni referenci analize satelitskih posnetkov v zadnjih treh letih."
        output.append(dict(id=f"satellite-v{version}", tender_id="satellite", version=version, title="Platforma za analizo satelitskih posnetkov", summary="Razvoj podatkovne platforme za spremljanje vegetacije s satelitskimi posnetki, analitiko in kartografskim prikazom.", requirements=[req("satellite-reference", f"Najmanj {'ena' if count == 1 else 'dve'} primerljivi referenci", "reference_count", "satellite", count, max_age_years=3, quote=text)], criteria=[{"title":"Ponudbena cena", "weight":50},{"title":"Kakovost analitične metodologije", "weight":40},{"title":"Načrt prenosa znanja", "weight":10}],
             scope="Predmet je razvoj platforme za analizo satelitskih posnetkov in spremljanje stanja vegetacije. Vključeni so obdelava časovnih vrst, zaznavanje sprememb, strojno učenje, pregled rezultatov na zemljevidu in izvoz podatkov prek API. Rešitev je namenjena strokovnim uporabnikom in javnim organizacijam.",
             delivery="Predvidena izvedba traja osem mesecev. Oddaja vključuje metodologijo, izvorno kodo, načrt validacije in dokumentacijo. " + ("Ta različica ohranja prvotni referenčni pogoj." if version == 1 else "POPRAVEK: zahteva glede števila primerljivih referenc se spremeni z ene na dve. Drugi pogoji in merila ostanejo enaki.")))
    for doc in output:
        for r in doc["requirements"]:
            r["document_id"] = doc["id"]
        doc["pages"] = [
            {"page":1,"heading":"Predmet in obseg naročila", "text":f"{common}\n\n{doc['scope']}\n\n{doc['delivery']}"},
            {"page":2,"heading":"Pogoji za sodelovanje", "text":"\n\n".join(r["quote"] for r in doc["requirements"]) + "\n\nVsaka referenca mora biti potrjena in primerljiva po vsebini. Če podatek ni naveden, izpolnjevanja pogoja ni mogoče potrditi. Podatki o izmišljenem demo podjetju se preverjajo ločeno od tega dokumenta."},
            {"page":3,"heading":"Merila za izbor in dokazila", "text":"\n\n".join(f"{c['title']}: {c['weight']} %." for c in doc["criteria"]) + "\n\nMerila za izbor se uporabijo za vrednotenje ponudb. Izpolnitev pogojev za sodelovanje je ločena presoja. Ponudnik predloži seznam referenc, opis projektne ekipe, predlog izvedbe in finančno ponudbo.\n\nDatumi objave in roki so za demonstracijo prikazani v aplikaciji. Dokument služi preverjanju ekstrakcije besedila, strani in dokazov."},
        ]
    return output


def render(doc):
    navy, blue, gray = colors.HexColor("#14243b"), colors.HexColor("#4358d5"), colors.HexColor("#627189")
    styles = {
        "kicker":ParagraphStyle("kicker",fontName="RadarBold",fontSize=9,leading=13,textColor=blue,spaceAfter=13),
        "title":ParagraphStyle("title",fontName="RadarBold",fontSize=25,leading=32,textColor=navy,spaceAfter=24),
        "h":ParagraphStyle("heading",fontName="RadarBold",fontSize=16,leading=22,textColor=navy,spaceAfter=18),
        "body":ParagraphStyle("body",fontName="Radar",fontSize=10.5,leading=17,textColor=navy,spaceAfter=17),
        "small":ParagraphStyle("small",fontName="Radar",fontSize=9,leading=14,textColor=gray),
    }
    def page(canvas, _):
        canvas.saveState()
        canvas.setFillColor(blue)
        canvas.rect(21*mm, A4[1]-17*mm, 12*mm, 2*mm, fill=1, stroke=0)
        canvas.setFont("RadarBold",9)
        canvas.setFillColor(navy)
        canvas.drawString(21*mm,A4[1]-25*mm,"RAZPISNI RADAR")
        canvas.setFont("Radar",8)
        canvas.setFillColor(gray)
        canvas.drawRightString(A4[0]-21*mm,A4[1]-25*mm,"DEMO DOKUMENTACIJA")
        canvas.setStrokeColor(colors.HexColor("#dce2ec"))
        canvas.line(21*mm,20*mm,A4[0]-21*mm,20*mm)
        canvas.setFont("Radar",8)
        canvas.drawString(21*mm,14*mm,f"{doc['id']}  |  Različica {doc['version']}  |  Izmišljen primer")
        canvas.drawRightString(A4[0]-21*mm,14*mm,f"{canvas.getPageNumber()} / 3")
        canvas.restoreState()
    story=[]
    for p in doc["pages"]:
        if p["page"] > 1:
            story.append(PageBreak())
        story += [Paragraph(f"{doc['id'].upper()} / RAZLIČICA {doc['version']}",styles["kicker"])]
        if p["page"] == 1:
            story.append(Paragraph(doc["title"],styles["title"]))
        story.append(Paragraph(f"0{p['page']}  {p['heading']}",styles["h"]))
        for para in p["text"].split("\n\n"):
            story.append(Paragraph(para,styles["body"]))
    SimpleDocTemplate(str(OUT/f"{doc['id']}.pdf"),pagesize=A4,leftMargin=21*mm,rightMargin=21*mm,topMargin=39*mm,bottomMargin=29*mm,title=doc["title"],author="Razpisni radar - izmišljen demo",pageCompression=1).build(story,onFirstPage=page,onLaterPages=page)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    fonts()
    for doc in documents():
        render(doc)
        (OUT/f"{doc['id']}.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"Created {doc['id']}: 3 pages")


if __name__ == "__main__":
    main()
