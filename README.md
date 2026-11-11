# Razpisni radar

Lokalni hackathon prototip, ki poveže javne razpise s profilom podjetja ter pokaže razloge, pogoje in spremembe. Vključuje delujoč zajem e-Naročanja in jasno označene demo primere. Podjetja poiščete v javnem naboru AJPES / PRS prek OPSI, brez API ključa.

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

Za samodejni zajem ob zagonu in nato vsakih 12 ur vključite dodatni proces:

```bash
docker compose --profile sync up --build
```

Privzeti zagon zunanjega portala ne osvežuje samodejno. Docker uporablja svoj podatkovni nosilec; podatki lokalnega Python zagona se vanj ne prenesejo samodejno.

## Kaj lahko preizkusite

- **Razpisi:** vsebinska priporočila, kombiniranje naprednih filtrov, shranjena iskanja, sortiranje in spremljanje.
- **Podrobnosti:** razlaga ujemanja, pogoji `izpolnjen / neizpolnjen / neznan`, merila, sklopi, PDF-ji in dokaz na konkretni strani.
- **Profil:** iskanje resničnih podjetij v AJPES prek OPSI, predogled osnovnih podatkov ter urejanje dejavnosti, tehnologij, referenc, kadrov, zmogljivosti in preferenc. Sprememba profila spremeni presojo razpisov.
- **AI pomočnik:** priporočila, primerjava izbranih razpisov, vprašanja o pogojih in predlogi profila oziroma filtrov, ki jih uporabnik potrdi.
- **Obvestila:** nova relevantna objava, popravek pogoja in podaljšanje roka. Dogodki so idempotentni; ponovitev istega popravka ne doda drugega obvestila.

Napredne filtre odprete z gumbom **Filtri**. Skupine se razširijo na klik; aktivne skupine imajo oznako števila izbir. **Shranjena iskanja** in **Iskanje z opisom** sta pod iskalnikom. Na kartici odprite **Zakaj ta ocena?** za razloge in odprta vprašanja. Profil je razdeljen na štiri zavihke; osnutek ostane ohranjen med preklapljanjem, spremembe pa potrdite s **Shrani profil**.

## Petminutna predstavitev

1. Odprite profil. Demo podjetje ima energetsko referenco v vrednosti 120.000 EUR, športno referenco brez vrednosti in datuma ter eno satelitsko referenco. Gre izključno za izmišljene podatke.
2. Na razpisih uporabite filtre za spletne platforme, IoT in podatke. Shranite iskanje in preverite, da je po osvežitvi še vedno na voljo.
3. Odprite energetski razpis. Pri pogoju izberite dokaz in odprite drugo stran PDF-ja.
4. Odprite športni portal. Manjkajoča vrednost oziroma datum reference morata ostati označena kot neznana. Dopolnite referenco z vrednostjo 80.000 EUR in letom znotraj zadnjih treh let ter znova preverite pogoje. Za novo priporočilo športnega portala je potreben tudi ISO 27001.
5. V AI pomočniku izberite »Poišči primerne razpise«, »Preveri pogoje za prijavo« ali »Primerjaj dva razpisa«. Pri zadnjih dveh možnostih vas vmesnik vodi skozi izbiro razpisov.
6. V meniju **Podatki in demo** sprožite demo popravek satelitskega razpisa. Zahteva se spremeni z ene na dve referenci. Odprite obvestilo ter primerjavo stare in nove različice.
7. Ponovite isti dogodek in preverite, da novega obvestila ni. Za naslednjo predstavitev uporabite ponastavitev demo stanja.

## Predlogi za razvoj podjetja

V **Obvestila → Predlogi za razvoj** aplikacija sama predlaga izboljšave iz obdelanih pogojev razpisov. Podprti so certifikati, primerljive reference, velikost ekipe in tehnologije. Neznani podatki o ekipi oziroma referencah sprožijo predlog za dopolnitev profila, ne samodejne zahteve po novih zmogljivostih. Pri certifikatu, ki ni naveden, najprej preverite, ali ga podjetje že ima.

Izberite **Poglej učinek** za primerjavo zdaj → po izboljšavi, preostale ovire in povezave na dokumentacijo. **Odprti razpisi** in **Pretekli razpisi** imajo ločeni štetji; demo predlogi so ločeni od resničnih. Število dodatno izpolnjenih pogojev ni verjetnost uspeha ali jamstvo upravičenosti. Prikaz uporablja shranjene analize in ne kliče AI ali zunanjih virov. Resnična dokumentacija brez analize ne ustvarja izmišljenih predlogov.

Predlog poimenujte in shranite v **Shranjeni načrti**. Z gumbom **Združi predloge** odprite izbiro in združite več predlogov istega vira; dodate jih lahko tudi obstoječemu načrtu. Ob odprtju se načrt preračuna na aktualnem profilu in dokumentaciji. Predpostavljene reference so zaključene in potrjene letos; čas pridobivanja kompetenc ni ocenjen. Dejanski profil ostane nespremenjen. Načrti so vezani na identiteto podjetja in se ob menjavi podjetja skrijejo; to ni produkcijska večuporabniška avtorizacija. Demo ponastavitev ohrani shranjene načrte, njihov učinek pa znova izračuna.

Predlogi se osvežijo ob naslednjem preverjanju obvestil (v odprti aplikaciji vsakih 30 sekund). Enak predlog se ne podvaja. Ponovno postane neprebran, ko pomaga pri dodatnem odprtem razpisu ali nastane dodatno priporočilo. Prikazanih je največ pet najkoristnejših neshranjenih predlogov; shranjeni predlogi ostanejo dosegljivi. Zgodovinski pogled primerja današnji profil s shranjenimi pogoji zaključenih razpisov in ne napoveduje prihodnjih objav.

**Kratek demo:** v začetnem profilu odprite obvestilo za ISO 27001. Pokaže dodaten pogoj pri športnem portalu ter ločeno pri zaključeni občinski aplikaciji. Športne reference ostanejo neznane. Združite predlog z dopolnitvijo referenc, shranite načrt in osvežite stran. Po dejanskem dopolnjevanju profila se učinek načrta zmanjša oziroma izgine. Za demonstracijo nove reference sprožite popravek satelitskega razpisa.

Pri nadgradnji ponovno zaženite `./scripts/dev.sh`: izvede migracijo in osveži vključene demo PDF-je brez ponastavitve profila. PDF povezave vsebujejo `#page=...`; nekatere razširitve brskalnika (npr. Adobe Acrobat) fragment prezrejo, zato sta številka strani in citat navedena tudi ob povezavi.

## Podatki in meje prototipa

Začetni nabor vsebuje šest **izmišljenih demo razpisov** in en **resničen arhivski zapis**. Zajem doda dejanske objave. S filtrom **Izvor in stanje → e-Naročanje / Demo primeri** jih lahko ločite. Za štiri demo razpise so priloženi kratki besedilni PDF-ji, satelitski razpis pa ima še popravljeno različico. Demo datumi se ob prvi pripravi oziroma ponastavitvi izračunajo glede na datum v časovnem pasu Europe/Ljubljana. Datumi resničnega arhiva se ne premikajo. Ponastavitev demo stanja ohrani resnične uvožene objave in njihova obvestila.

Arhivski zapis je »Razvoj in vzdrževanje spletne platforme IJS z informacijskim in uredniškim sistemom«, `JN006195/2026-EUe16/01`, z rokom 7. 9. 2026 ob 10.00 ter stanjem **Ustavljeno**, preverjenim 10. 11. 2026. Ne predstavlja aktualne priložnosti. [Izvorni e-JN zapis](https://ejn.gov.si/ponudba/pages/aktualno/aktualno_jnc_podrobno.xhtml?zadevaId=77669).

### Zajem e-Naročanje

V zgornji vrstici izberite **Podatki in demo → Osveži razpise iz e-Naročanja**:

- **Nove objave:** prenese največ 20 zadnjih objav iz zadnjih sedmih dni in preveri zadnje različice do 30 spremljanih dosjejev. Priloge prvih treh objav se prenesejo samodejno.
- **Po povezavi:** uvozi eno objavo po ID-ju oziroma URL-ju, skupaj z dostopno dokumentacijo na portalu.

Oba načina in samodejni proces si delijo omejitev **dveh zagonov zajema na slovenski koledarski dan**. Štejejo tudi neuspešni zagoni. Stanje povezave, datum zadnjega uspešnega zajema in preostali zagoni so vidni v oknu uvoza. En zagon lahko vsebuje več zahtev. Omejitev prototipa je največ 50 objav na ročni CLI zagon, do 30 spremljanih dosjejev in približno minuta obdelave; delni zajem je označen. To ni celovita zgodovina vseh javnih naročil.

Zajem lahko zaženete tudi iz korena projekta:

```bash
.venv/bin/python backend/manage.py sync_pjn
.venv/bin/python backend/manage.py sync_pjn --notice 'https://www.enarocanje.si/#/pregled-objav/1229976'
.venv/bin/python backend/manage.py sync_pjn --watch
```

Izberite ustrezen ukaz; vsak neposredni zajem porabi en dnevni zagon. `--watch` zajema ob zagonu in vsakih 12 ur, dokler proces teče. Pri običajnem `./scripts/dev.sh` samodejni zajem ni vključen.

Adapter uporablja javni API uradnega portala, shranjuje izvorne odzive ter povezuje različice po dosjeju. Ponovni uvoz iste različice ne doda obvestila, starejša objava pa ne prepiše novejše. Spremembe spremljanih dosjejev ustvarijo obvestilo tudi po zaključku naročila. Če prejšnja različica še ni shranjena, pokažemo izvorni opis popravka brez izmišljene primerjave.

Preslikava polj in šifranti CPV, vrste naročila, faze, lokacije ter valute so preverjeni na dejanskih odzivih. Posnetek šifrantov je v `backend/source_data/pjn-codelists.json`, zajet 10. 11. 2026; ne osvežuje se samodejno. Neznane vrednosti ostanejo neznane. Status objave »Objavljen« sam ne pomeni odprtega roka. Širša CPV kategorija sama ne zadošča za visoko vsebinsko ujemanje; trenutno gre za razložljivo hevristiko, ne za potrjeno presojo sposobnosti podjetja.

Ob omrežni napaki se ohranijo shranjeni podatki in pokaže opozorilo. Uspešen zajem metapodatkov ne pomeni, da so že preverjeni vsi pogoji dokumentacije.

Vir: **Javne informacije Slovenije – portal javnih naročil**. [OPSI: dokumentacija API in pogoji ponovne uporabe](https://podatki.gov.si/dataset/api-pjn).

### Predizpolnitev podjetja: AJPES prek OPSI

**Povezava deluje brez računa in brez API ključa.** Uporabljamo javni nabor Poslovnega registra Slovenije, ki ga AJPES objavlja na OPSI. To je dvakrat mesečno osvežena zbirka; ne gre za sproten dostop do celotnega ePRS oziroma naročniški `restPrsInfo`.

1. Odprite **Profil podjetja** in vnesite ime ali 7- oziroma 10-mestno matično številko.
2. Izberite pravi poslovni subjekt. Poslovne enote so ločeni zadetki z lastno matično številko in oznako pravne oblike.
3. Preverite predogled in izberite **Uporabi podatke**. V obrazec se prenesejo **naziv, matična številka in naslov**.
4. Dopolnite dejavnost, spletno stran, reference, kadre in tehnologije ter izberite **Shrani in osveži priporočila**.

Odprti nabor ne vsebuje dejavnosti SKD, spletne strani, prihodkov, referenc, certifikatov ali zmogljivosti. Teh podatkov ne sklepamo iz naziva. Ob izbiri drugega podjetja se obrazec začne brez prejšnjih referenc in kompetenc, kar je v predogledu izrecno navedeno. Osvežitev iste matične številke ohrani uporabniške dopolnitve. Iskanje in predogled ne spreminjata shranjenega profila; podatki se shranijo šele z uporabnikovo potrditvijo obrazca.

Vsako uvoženo osnovno polje ima oznako vira. Ročna sprememba polja spremeni njegovo oznako v uporabniški vnos. Izvor, datum prevzema, datum posodobitve metapodatkov zbirke in licenca se ohranijo po osvežitvi aplikacije. Prisotnost v objavljenem naboru sama ne potrjuje trenutnega statusa, bonitete ali sposobnosti podjetja za prijavo.

Iskanje uporablja OPSI `datastore_search`, vrne največ 20 zadetkov in pokaže skupno število. Pri imenu gre za besedilno iskanje po naboru; za natančen zadetek uporabite matično številko. Iskanje podjetij ne porablja dnevnih zagonov e-Naročanja. Odgovore hranimo lokalno 24 ur, zato ponovljeno iskanje ne povzroči nove zunanje zahteve. Ob izpadu se že shranjeni rezultati prikažejo z opozorilom in prvotnim datumom; če shranjenega rezultata ni, aplikacija jasno sporoči napako in omogoča ročni vnos. Nobeno neuspešno iskanje ne vrne izmišljenega podjetja. **Demo predloga** ostaja ločen, izrecen gumb.

Vir: **Poslovni register Slovenije, AJPES, prek OPSI**, licenca **CC BY 4.0**. [Zbirka in pogoji ponovne uporabe](https://podatki.gov.si/dataset/poslovni-register-slovenije), [opis odprtega nabora pri AJPES](https://www.ajpes.si/registri/poslovni_register/splosno). Bizi je odstranjen iz uporabniškega toka in ni potreben.

### Dokumenti in razlaga

Zajem prenese javne priloge z uradne poti `/api/datoteka/get`. Podpira besedilne PDF-je in ZIP arhive. Omejitve: 10 MB na prenos, do 30 datotek in 20 MB razpakirane vsebine, do 150 strani na PDF. Zunanje povezave na druge strežnike in omejeno dostopna dokumentacija zahtevajo ročni pregled. Word, Excel, skenirani ali zaščiteni dokumenti ostanejo označeni kot neobdelani.

`pypdf` izlušči besedilo po straneh. **Prenos besedila in AI analiza pogojev sta ločena koraka.** Za dejansko AI ekstrakcijo potrebujete ključ ter gumb za osvežitev analize na zavihku Pogoji. Brez ključa se pogoji resničnih dokumentov ne izmišljajo. Priložene demo datoteke JSON vsebujejo pripravljeno strukturirano analizo; povezave na dokaze se preverijo glede na dejansko besedilo PDF-ja. Stara dokumentacija ne potrjuje pogojev nove različice objave.

Vsebinsko ujemanje je ločeno od preverjanja obveznih pogojev; manjkajoči podatki niso dokaz izpolnitve. Analiza zajema obdelane pogoje, ne zagotavlja popolnosti celotne dokumentacije ali uspeha prijave.

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

Preverjeno pri izvedbi: 97 avtomatskih testov, produkcijska gradnja in lokalni zagon. **Živi zajem e-Naročanja je bil uspešno izveden 10. 11. 2026:** 20 novih resničnih zapisov, 6 shranjenih datotek, 94 strani izluščenega besedila in 2 neobdelani prilogi. Ti prenosi so v lokalni bazi in medijskih datotekah, ne v Gitu; nov klon projekta jih pridobi z zajemom. Testi uporabljajo tudi vzorčna odziva dejanskega API-ja.

Konfiguracija Compose je veljavna; zagon vsebnikov ni bil preverjen, ker Docker Engine ni bil zagnan. Živi OpenAI klici niso bili preizkušeni brez ključa. Živo iskanje AJPES prek OPSI in predogled po matični številki sta bila uspešno preverjena 10. 11. 2026. Neposredni naročniški API AJPES in Bizi nista uporabljena.

To je lokalni prototip z enim uporabnikom. Produkcijska prijava, izolacija podjetij, pošiljanje e-pošte, OCR in celovit zajem vseh objav ter prilog so nadaljnji koraki pred javno uporabo.
