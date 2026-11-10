# Razpisni radar

Lokalni hackathon prototip, ki poveže javne razpise s profilom podjetja ter pokaže razloge, pogoje in spremembe. Splošna rešitev v slovenščini, z izmišljenim tehnološkim podjetjem in jasno označenimi demo podatki.

## Hiter zagon

Potrebujete **Python 3.10+** (priporočeno 3.12), **Node.js 22+** in npm.

```bash
./scripts/setup.sh
./scripts/dev.sh
```

Odprite **http://localhost:5174**. Django API teče na `127.0.0.1:8001`, Vite posreduje zahteve `/api`. Ctrl+C ustavi lokalni razvojni zagon. Skripta za pripravo ustvari virtualno okolje, namesti odvisnosti, izvede migracije in pripravi začetni nabor. Ponovni običajni zagon ne ponastavi vašega profila ali spremljanja.

Na sistemu z več različicami Pythona lahko uporabite `PYTHON_BIN=/pot/do/python3.12 ./scripts/setup.sh`.

Če sta vrata že zasedena, izberite druga, na primer `RADAR_BACKEND_PORT=8002 RADAR_FRONTEND_PORT=5175 ./scripts/dev.sh`. Skripta bo ustrezno povezala vmesnik in API.

### Docker

```bash
docker compose up --build
```

Aplikacija je na istem naslovu **http://localhost:5174**. SQLite, naložene datoteke in uporabniške spremembe ostanejo v nosilcu `radar-data`. Zaustavitev: `docker compose down`. Potreben je delujoč Docker Engine oziroma Docker Desktop. API ni objavljen neposredno zunaj Docker omrežja; spletni port je vezan na lokalni računalnik.

## Kaj lahko preizkusite

- **Razpisi:** vsebinska priporočila, kombiniranje naprednih filtrov, shranjena iskanja, sortiranje in spremljanje.
- **Podrobnosti:** razlaga ujemanja, pogoji `izpolnjen / neizpolnjen / neznan`, merila, sklopi, PDF-ji in dokaz na konkretni strani.
- **Profil:** predogled demo predizpolnitve, urejanje dejavnosti, tehnologij, referenc, kadrov, zmogljivosti in preferenc. Sprememba profila spremeni presojo razpisov.
- **AI svetovalec:** priporočila, primerjava izbranih razpisov, vprašanja o pogojih in predlogi profila oziroma filtrov, ki jih uporabnik potrdi.
- **Obvestila:** nova relevantna objava, popravek pogoja in podaljšanje roka. Dogodki so idempotentni; ponovitev istega popravka ne doda drugega obvestila.

## Petminutna predstavitev

1. Odprite profil. Demo podjetje ima energetsko referenco v vrednosti 120.000 EUR, športno referenco brez vrednosti in datuma ter eno satelitsko referenco. Gre izključno za izmišljene podatke.
2. Na razpisih uporabite filtre za spletne platforme, IoT in podatke. Shranite iskanje in preverite, da je po osvežitvi še vedno na voljo.
3. Odprite energetski razpis. Pri pogoju izberite dokaz in odprite drugo stran PDF-ja.
4. Odprite športni portal. Manjkajoča vrednost oziroma datum reference morata ostati označena kot neznana. Dopolnite referenco z vrednostjo 80.000 EUR in letom znotraj zadnjih treh let ter znova preverite pogoje.
5. V svetovalcu vprašajte po najboljših priložnostih ali primerjajte dva izbrana razpisa.
6. Sprožite demo popravek satelitskega razpisa. Zahteva se spremeni z ene na dve referenci. Odprite obvestilo ter primerjavo stare in nove različice.
7. Ponovite isti dogodek in preverite, da novega obvestila ni. Za naslednjo predstavitev uporabite ponastavitev demo stanja.

## Podatki in meje prototipa

V naboru je šest **izmišljenih demo razpisov** in en **resničen arhivski zapis**. Za tri demo razpise so priloženi kratki besedilni PDF-ji, satelitski razpis pa ima še popravljeno različico. Demo datumi se ob prvi pripravi oziroma ponastavitvi izračunajo glede na datum v časovnem pasu Europe/Ljubljana. Datumi resničnega arhiva se ne premikajo.

Arhivski zapis je »Razvoj in vzdrževanje spletne platforme IJS z informacijskim in uredniškim sistemom«, `JN006195/2026-EUe16/01`, z rokom 7. 9. 2026 ob 10.00 ter stanjem **Ustavljeno**, preverjenim 10. 11. 2026. Ne predstavlja aktualne priložnosti. [Izvorni e-JN zapis](https://ejn.gov.si/ponudba/pages/aktualno/aktualno_jnc_podrobno.xhtml?zadevaId=77669).

### Zajem e-Naročanje

Uvoz po ID-ju oziroma URL-ju uporablja uradni endpoint za posamezno objavo. Adapter shranjuje izvorni odziv in omejuje zunanje sinhronizacije na največ dvakrat dnevno. Dostop do zunanjega vira lahko v omrežju odpove; aplikacija takrat vrne označen shranjen arhivski primer ali jasno napako, ne izmišljene nove objave. Celovit zajem seznama novih objav in vseh zunanjih prilog ni del te različice.

Vir: **Javne informacije Slovenije – portal javnih naročil**. [OPSI: dokumentacija API in pogoji ponovne uporabe](https://podatki.gov.si/dataset/api-pjn).

### Predizpolnitev podjetja

Predizpolnitev je **demo adapter**, ki uporablja izmišljene podatke in ne dostopa do Bizi. Pred shranjevanjem uporabnik vidi predogled. Pravi Bizi API zahteva ustrezen dostop in dogovor; ni delujoč brez njiju. [Bizi API](https://www.bizi.si/storitve/API-dostop/).

### Dokumenti in razlaga

`pypdf` izlušči besedilo po straneh. Priložene datoteke JSON vsebujejo pričakovano strukturirano demo analizo; povezave na dokaze se preverijo glede na dejansko izluščeno besedilo PDF-ja. Skenirani PDF-ji brez besedila in nepodprte priloge ostanejo označeni kot neobdelani. Vsebinsko ujemanje je ločeno od preverjanja obveznih pogojev; manjkajoči podatki niso dokaz izpolnitve. Analiza zajema obdelane pogoje, ne zagotavlja popolnosti celotne dokumentacije ali uspeha prijave.

Demo PDF-je lahko ponovno ustvarite z:

```bash
.venv/bin/python backend/generate_demo_documents.py
```

Za generiranje potrebujete DejaVu Sans na Linuxu ali Arial na macOS; že vključeni PDF-ji teh fontov na računalniku uporabnika ne zahtevajo.

## Priklop jezikovnega modela

Brez API ključa aplikacija deluje v jasno označenem **demo načinu** z odgovori, sestavljenimi iz trenutnega profila, analiz in izvornih odlomkov.

Za žive strežniške klice kopirajte `.env.example` v `.env` in nastavite:

```dotenv
OPENAI_API_KEY=vas-kljuc
OPENAI_MODEL=gpt-4.1-mini
```

Znova zaženite Django oziroma Docker. Model je nastavljiv. Ključ se nikoli ne pošlje brskalniku in `.env` je izključen iz različic. Integracija uporablja Responses API, JSON Schema in strežniško preverjanje sklicev; pri nedosegljivem modelu je prehod na demo odgovor označen. Živi model prejme ustrezne podatke profila in odlomke dokumentacije, zato za javni demo uporabljajte izmišljene podatke.

## Razvoj in preverjanje

```bash
./scripts/check.sh
```

Skripta izvede Django sistemski pregled, teste domenske logike/API, TypeScript preverjanje, produkcijsko gradnjo React aplikacije in preverjanje Compose konfiguracije. Za zadnji korak je potreben Docker CLI; zagon Docker daemona za preverjanje konfiguracije ni potreben.

Projekt je organiziran v `frontend/` in `backend/`. Vmesniki in podatkovni objekti so opisani v [CONTRACT.md](CONTRACT.md). SQLite podatki, naložene datoteke, ključi in razvojno okolje niso vključeni v izvorno kodo.

Preverjeno pri izvedbi: 50 avtomatskih testov, produkcijska gradnja, lokalni zagon ter ključni uporabniški tokovi v namiznem in mobilnem prikazu brskalnika. Konfiguracija Compose je veljavna; zagon vsebnikov ni bil preverjen, ker Docker Engine ni bil zagnan. Živi OpenAI klici niso bili preizkušeni brez ključa. Dostop do API e-Naročanje je v razvojnem omrežju vrnil napako posredniškega strežnika HTTP 407, zato je adapter preverjen s testnimi odzivi in shranjenim arhivom; dejansko obliko živega odziva je treba potrditi ob uspešni povezavi.

To je lokalni prototip z enim uporabnikom. Produkcijska prijava, izolacija podjetij, pošiljanje e-pošte, OCR in celovit samodejni zajem so nadaljnji koraki pred javno uporabo.
