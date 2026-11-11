# Razpisni radar

**Je ta javni razpis za nas?** Razpisni radar poveže javna naročila s profilom podjetja in pokaže, zakaj je priložnost zanimiva, kateri pogoji so izpolnjeni in kaj je treba še preveriti.

Prototip za **hackathon, izziv št. 2: podatkovno inženirstvo in AI za javna naročila**. React, TypeScript, Django REST Framework in SQLite. Za predstavitev deluje tudi brez API ključev.

## Kaj ponuja

- **Pregled priložnosti:** priporočeni in spremljani razpisi, neprebrana obvestila ter prihajajoči roki.
- **Iskanje:** ključne besede, CPV, naročnik, lokacija, vrednost, roki, izvor, stanje in prag ujemanja. Napredni filtri se odprejo po potrebi; iskanja lahko shranite.
- **Razložljiva presoja:** vsebinsko ujemanje 0–100, ločen pregled obveznih pogojev in dokazi z navedbo dokumenta ter strani.
- **Profil podjetja:** osnovni podatki iz AJPES prek OPSI; reference, znanja, certifikati in ekipa so uporabniški vnosi. Dejavnost, opis, znanja in tehnologije lahko predlaga branje spletne strani podjetja, vsak predlog z dobesednim virom.
- **AI pomočnik:** priporočila, preverjanje pogojev, primerjava razpisov in predlogi filtrov oziroma dopolnitve profila, ki jih uporabnik potrdi.
- **Spremljanje:** spremembe pogojev, podaljšanja rokov in nove priložnosti brez podvajanja istega dogodka.
- **ESPD osnutek:** zavihek ESPD na razpisu predizpolni podatke o naročilu, podjetju (AJPES, profil) in pogojih iz dokumentacije s predlogi odgovorov. Razlogov za izključitev ne izpolni samodejno. Izvoz v PDF (tisk) in JSON.
- **Partnerji in razvoj:** potencialna dopolnitev pogojev s partnerjem ter shranjeni načrti za razvoj kompetenc.

Vmesnik uporablja stalno navigacijo, berljive kartice in vidno utemeljitev ocene ter se prilagaja manjšim zaslonom. Oblikovalski referenci sta preglednost poslovnih platform [PRIOT](https://www.priot.io/) in poenostavitev vsakodnevnih opravil v [Telesporju](https://www.priot.io/projects/telespor-user-portal). Projekt ni povezan s podjetjem PRIOT.

## Lokalni zagon

Potrebujete **Python 3.10+** (priporočeno 3.12), **Node.js 22+** in npm. Ukaze izvajajte v korenu projekta.

### Windows / PowerShell

Priprava ob prvem zagonu:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm.cmd --prefix frontend ci
.\.venv\Scripts\python.exe backend/manage.py migrate --noinput
.\.venv\Scripts\python.exe backend/manage.py seed_demo
```

V prvem terminalu zaženite API:

```powershell
.\.venv\Scripts\python.exe backend/manage.py runserver 127.0.0.1:8001
```

V drugem terminalu zaženite vmesnik:

```powershell
npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Odprite **http://localhost:5174**. Aktivacija virtualnega okolja ni potrebna. Ob naslednjem zagonu zadoščata zadnja dva ukaza; po posodobitvi projekta po potrebi ponovite namestitev odvisnosti, migracije in `seed_demo`.

### Linux / macOS

```bash
./scripts/setup.sh
./scripts/dev.sh
```

Vmesnik je na **http://localhost:5174**, API na `127.0.0.1:8001`. Vite posreduje zahteve `/api` v Django. Ctrl+C ustavi razvojni zagon. Za druga vrata: `RADAR_BACKEND_PORT=8002 RADAR_FRONTEND_PORT=5175 ./scripts/dev.sh`.

### Docker

```bash
docker compose up --build
```

Odprite **http://localhost:5174**. Podatki ostanejo v nosilcu `radar-data`; zaustavitev je `docker compose down`. Docker uporablja ločeno bazo od lokalnega Python zagona. Za zajem ob zagonu in nato vsakih 12 ur:

```bash
docker compose --profile sync up --build
```

Običajni zagon ne sproži zunanjega zajema. `seed_demo` ohrani shranjeni profil in spremljanje; ponastavitev je izrecna akcija v meniju **Demo**.

## Petminutna predstavitev

1. **Profil podjetja:** pokažite izmišljeno podjetje Lumina digital in njegove reference. Športna referenca namenoma nima vrednosti in datuma.
2. **Razpisi:** preglejte priporočila, razloge na karticah, rok in vrednost. Preizkusite filtre ali shranite iskanje.
3. **Energetski razpis → Pogoji:** odprite dokaz na konkretni strani PDF-ja. Pokažite razliko med vsebinsko oceno in preverjanjem pogojev.
4. **Športni portal:** manjkajoči podatki ostanejo neznani. Dopolnite referenco z vrednostjo 80.000 EUR in letom znotraj zadnjih treh let. Za priporočilo je potreben tudi ISO 27001.
5. **AI pomočnik:** izberite primerjavo dveh razpisov. Brez ključa je odgovor označen kot demo.
6. **Demo → Popravek referenčnega pogoja:** satelitski razpis zahteva dve referenci namesto ene. Odprite obvestilo in primerjavo spremembe. Ponovitev dogodka ne doda novega obvestila.

Za razširjeno predstavitev odprite **Partnerji** v razpisu ali **Obvestila → Predlogi za razvoj**. [Kratka predstavitvena zgodba](PITCH_PREGLED_APLIKACIJE.md).

## Podatkovni tok

```text
e-Naročanje → zajem in povezava različic → normalizirani metapodatki
           → PDF / ZIP → besedilo po straneh → analiza pogojev in dokazov
Profil podjetja + razpis → vsebinsko ujemanje + presoja pogojev
                        → priporočilo, razlaga in obvestila
```

### e-Naročanje

Gumb **Osveži razpise** odpre zajem zadnjih objav ali uvoz po povezavi. Privzeti zajem prenese do 20 objav iz zadnjih sedmih dni, preveri do 30 spremljanih dosjejev in prenese priloge prvih treh objav. Uvoz po povezavi prenese dostopno dokumentacijo izbrane objave.

Vsi načini si delijo omejitev **dveh zagonov na slovenski koledarski dan**; štejejo tudi neuspešni poskusi. Zadnji uspešni zajem in preostali zagoni so prikazani v oknu uvoza. Ob izpadu ostanejo shranjeni podatki dostopni. Šifranti v `backend/source_data/` so posnetek in se ne osvežujejo samodejno.

Vir: **Javne informacije Slovenije – portal javnih naročil**. [Dokumentacija API in pogoji ponovne uporabe](https://podatki.gov.si/dataset/api-pjn).

### Dokumenti in AI

Podprti so besedilni PDF-ji in ZIP arhivi: največ 10 MB na datoteko, 30 članov oziroma 20 MB razpakirane vsebine in 150 strani na PDF. Skeni, zaščiteni dokumenti in nepodprti formati ostanejo označeni za dodaten pregled. Izluščeno besedilo še ne pomeni analize pogojev.

Za živo analizo kopirajte `.env.example` v `.env` in nastavite `OPENROUTER_API_KEY` (privzeti model `openai/gpt-6-luna`, spremenljiv z `OPENROUTER_MODEL`) ali `OPENAI_API_KEY` in `OPENAI_MODEL`, nato znova zaženite backend. Če sta nastavljena oba, ima prednost OpenRouter; zahteve gredo samo k ponudnikom s strukturiranim izhodom, ki ne zbirajo podatkov za učenje. Citati v odgovorih se dobesedno preverijo proti strani dokumenta, sicer je prikazan demo odgovor. Ključ ostane na strežniku; `.env` ni v Gitu. Model prejme ustrezne podatke profila in dokumentacije. Brez ključa se uporabljajo pripravljene demo analize in označeni demo odgovori; pogojev resničnih dokumentov aplikacija ne izmišljuje.

### Primerjava vsebinskega ujemanja

Orodje za razvijalce izmeri, kako dobro trije pristopi presodijo vsebinsko primernost razpisa: sedanja pravila s ključnimi besedami, LLM (OpenRouter oziroma OpenAI) in [Gemini Decisions API](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/). Aplikacije ne spreminja.

1. `backend/manage.py relevance_eval export` zapiše `backend/eval/relevance_labels.csv`: vsak resničen razpis iz baze v paru s štirimi **izmišljenimi** profili (IT, ceste, tiskarna, optična omrežja). Ponovni izvoz po novem zajemu doda nove vrstice in ohrani oznake.
2. V stolpec `label` vpišite `primeren` (jedrna dejavnost, podjetje bi naročilo izvedlo samo), `delno` (sorodno področje, potreben partner) ali `neprimeren`; dovolj so tudi `p`, `d`, `n`. Presojate samo predmet naročila, ne pogojev, vrednosti ali roka. Oznake naj določi človek, ne model.
3. `backend/manage.py relevance_eval run --show-errors` izpiše točnost, makro F1, natančnost in priklic za »primeren«, hude napake (primeren ↔ neprimeren) ter Brierjevo oceno za verjetnostne napovedi. `--out tmp/rezultati.json` shrani napovedi po vrsticah.

LLM se uporabi, če je nastavljen `OPENROUTER_API_KEY` ali `OPENAI_API_KEY`. Gemini zahteva `GEMINI_API_KEY` (model `GEMINI_DECISION_MODEL`, privzeto `gemini-decision-1`). Brez ključa se pristop preskoči. Ponudnikom se pošiljajo samo izmišljeni profili in javni metapodatki razpisov, nikoli shranjeni profil podjetja. Pri brezplačni ravni Gemini API lahko Google vsebino uporabi za izboljšave.

### Podjetja, partnerji in demo podatki

AJPES/OPSI povezava uporablja javni nabor PRS brez API ključa. Predizpolni samo **naziv, matično številko in naslov**. Rezultati se hranijo 24 ur. [Vir in licenca CC BY 4.0](https://podatki.gov.si/dataset/poslovni-register-slovenije).

Začetni nabor vsebuje šest izmišljenih razpisov, en resničen arhivski zapis in pet demo PDF-jev, vključno s popravljeno različico satelitskega razpisa. Datumi demo objav se določijo ob pripravi oziroma ponastavitvi; arhivski datumi ostanejo izvorni. **Demo oznake so vidne tudi na karticah in v prihajajočih rokih.** Arhivski zapis ni aktualna priložnost.

Partnerji prispevajo samo podatke s podprtimi dokazili. Uporabniška potrditev ni neodvisno preverjanje. Skupni potencial zahteva pregled dovoljenega načina skupne prijave. Razvojni načrti primerjajo predpostavke s trenutnimi pogoji in ne spreminjajo profila. Demo in resnični podatki se pri teh primerjavah ne mešajo.

## Struktura projekta

| Pot | Vsebina |
| --- | --- |
| `frontend/src/App.tsx` | Navigacija, iskanje, podrobnosti, profil in pomočnik |
| `frontend/src/OpportunityOverview.tsx` | Pregled priložnosti, spremljani roki in naslednji koraki |
| `frontend/src/NotificationsPage.tsx` | Obvestila in razvojni načrti |
| `frontend/src/Partners.tsx` | Partnerji in primerjava pogojev |
| `frontend/src/styles.css` | Skupni slogi in prilagoditve velikosti zaslona |
| `backend/tenders/pjn_*.py` | Zajem, normalizacija, različice in prenosi |
| `backend/tenders/matching.py` | Vsebinsko ujemanje in presoja pogojev |
| `backend/tenders/documents.py`, `ai.py` | Besedilo PDF, dokazi in AI |
| `backend/tenders/ajpes.py` | Iskanje podjetij in predpomnilnik |
| `backend/tenders/improvements.py`, `partners.py` | Razvojni načrti in partnerski potencial |
| `backend/tenders/espd.py`, `frontend/src/Espd.tsx` | ESPD osnutek |
| `backend/tenders/website.py`, `frontend/src/WebsiteImport.tsx` | Predlogi profila s spletne strani podjetja |
| `backend/tenders/relevance_eval.py`, `backend/eval/` | Primerjava pristopov za vsebinsko ujemanje na označenem naboru |
| `backend/demo_documents/`, `source_data/` | Demo dokumentacija in šifranti |
| `scripts/` | Priprava, zagon in preverjanje za Bash |

Podatkovni objekti, API in pravila so opisani v [CONTRACT.md](CONTRACT.md). SQLite baze, preneseni dokumenti, ključi in razvojna okolja so izključeni iz Gita.

## Preverjanje

Windows / PowerShell:

```powershell
.\.venv\Scripts\python.exe backend/manage.py check
.\.venv\Scripts\python.exe backend/manage.py test tenders --verbosity 1
npm.cmd --prefix frontend run build
```

Linux / macOS: `./scripts/check.sh` izvede iste preglede in še `docker compose config --quiet`; za slednjega je potreben Docker CLI. Gradnja vmesnika vključuje TypeScript preverjanje in zaznavanje neuporabljene kode.

## Delo z AI agenti

Na projektu sodeluje več ljudi in AI agentov. Pravila so v [AGENTS.md](AGENTS.md). Codex, Cursor in večina drugih agentov jo preberejo samodejno, Claude Code pa prek `CLAUDE.md`.

- **Git log je dnevnik sprememb.** Vsak commit ima poleg naslova telo: zakaj je bila sprememba narejena, katere odločitve so bile sprejete, migracije in konfiguracija, kaj je preverjeno in kaj ne ter kaj ostaja odprto. Predloga je v `.gitmessage`; vključite jo z `git config commit.template .gitmessage`.
- **Odprte točke** so na dnu `AGENTS.md`. Agent jih ob delu posodablja: rešene briše, nove dodaja.
- Spremembe API-ja se zapišejo tudi v CONTRACT.md.

Zgodovino z razlagami pregledate z `git log` (brez `--oneline`).

## Meje prototipa

Gre za lokalno aplikacijo za enega uporabnika. Vsebinsko ujemanje je razložljiva hevristika, ne verjetnost uspeha. Neznani pogoji ostanejo neznani; presoja zajema samo obdelano dokumentacijo. Produkcijska prijava in izolacija uporabnikov, OCR, pošiljanje e-pošte ter celovit zajem vseh objav niso vključeni.
