# RazpIzi

**Je ta javni razpis za nas?** RazpIzi poveže javna naročila s profilom podjetja in pokaže, zakaj je priložnost zanimiva, kateri pogoji so izpolnjeni in kaj je treba še preveriti.

Prototip za **hackathon, izziv št. 2: podatkovno inženirstvo in AI za javna naročila**. React, TypeScript, Django REST Framework in SQLite. Za predstavitev deluje tudi brez API ključev.

## Kaj ponuja

- **Pregled priložnosti:** priporočeni in spremljani razpisi, neprebrana obvestila ter prihajajoči roki.
- **Iskanje:** ključne besede, CPV, naročnik, lokacija, vrednost, roki, izvor, stanje in prag ujemanja. Napredni filtri se odprejo po potrebi; iskanja lahko shranite.
- **Razložljiva presoja:** vsebinsko ujemanje 0–100, ločen pregled obveznih pogojev in dokazi z navedbo dokumenta ter strani.
- **Gemini Decision 1 (izbirno):** ob nastavljenem ključu oceni vsebinsko primernost predmeta razpisa za profil podjetja. Ocena se shrani glede na profil, razpis in model. Če ključ manjka ali storitev ni dosegljiva, je uporaba obstoječih pravil vidno označena. Končno priporočilo še vedno ločeno preveri pogoje in stanje razpisa.
- **Profil podjetja:** osnovni podatki iz AJPES prek OPSI; reference, znanja, certifikati in ekipa so uporabniški vnosi. Dejavnost, opis, znanja in tehnologije lahko predlaga branje spletne strani podjetja, vsak predlog z dobesednim virom.
- **AI pomočnik:** priporočila, preverjanje pogojev, primerjava razpisov in predlogi filtrov oziroma dopolnitve profila, ki jih uporabnik potrdi.
- **Spremljanje:** spremembe pogojev, podaljšanja rokov in nove priložnosti brez podvajanja istega dogodka.
- **ESPD osnutek:** zavihek ESPD na razpisu predizpolni podatke o naročilu, podjetju (AJPES, profil) in pogojih iz dokumentacije s predlogi odgovorov. Razlogov za izključitev ne izpolni samodejno. Izvoz v PDF (tisk) in JSON.
- **Pretekle oddaje:** zavihek na resničnem razpisu pokaže podobna že oddana naročila z izbranimi ponudniki, številom ponudb, pogodbeno in ocenjeno vrednostjo ter razponom ponudb.
- **Partnerji in razvoj:** potencialna dopolnitev pogojev s partnerjem ter shranjeni načrti za razvoj kompetenc.

Vmesnik uporablja stalno navigacijo, berljive kartice in vidno utemeljitev ocene ter se prilagaja manjšim zaslonom. Oblikovalski referenci sta preglednost poslovnih platform [PRIOT](https://www.priot.io/) in poenostavitev vsakodnevnih opravil v [Telesporju](https://www.priot.io/projects/telespor-user-portal). Projekt ni povezan s podjetjem PRIOT.

## Lokalni zagon

Potrebujete **Python 3.10+** (priporočeno 3.12), **Node.js 22+** in npm. Ukaze izvajajte v korenu projekta.

Za razvoj Reacta in Djanga z lokalnim PostgreSQL uporabite
[`compose.dev.yaml`](compose.dev.yaml) in [`.env.local.example`](.env.local.example).
Compose zažene samo bazo; aplikacija teče lokalno. Postopek za Windows in macOS/Linux
je v [navodilih za lokalni razvoj](docs/local-development.md).
Spodnji običajni zagon brez `DATABASE_URL` uporablja SQLite.

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

### Novembrski arhivski cevovod (2026)

Ločen ukaz `scan_november` prebere vse strani novembrskega seznama objav, prenese dosegljivo dokumentacijo vsake objave in shrani preverljive odlomke, ki bi lahko pomenili samostojen sklop ali priložnost za dobavo oziroma podizvajanje. Uporabi trenutno shranjeni profil podjetja ali profil iz datoteke JSON. Prvi preizkus na dveh objavah:

```powershell
.\.venv\Scripts\python.exe backend/manage.py migrate --noinput
.\.venv\Scripts\python.exe backend/manage.py scan_november --max-notices 2
```

Za celoten november do dneva izvajanja odstranite `--max-notices`. Za drug profil lahko spremenite profil v aplikaciji ali podate svojo datoteko z `--profile`; `--terms "klime,hlajenje,prezračevanje"` doda iskalne izraze. Ukaz se lahko po prekinitvi ponovi: uspešno obdelane objave z istim profilom preskoči, `--refresh` pa jih prisilno ponovno obdela. Podrobno poročilo je v `backend/reports/2026-11.json`, pregled najdenih priložnosti za preglednico pa v `backend/reports/2026-11.csv`. Vsebujeta dokazne odlomke, dokument in stran oziroma del Office datoteke. JSON zabeleži tudi neprebrane priloge. Mapa poročil ni v Gitu. Novembra poročilo izrecno označi, da mesec še ni zaključen.

Zajem je omejen na javno dosegljive priloge z uradne domene: največ 50 MB na prenos ali član arhiva, 200 članov, 250 MB razširjene vsebine in globino dveh gnezdenih ZIP-ov. PDF-je bere do 500 strani, poleg njih še DOCX, XLSX, PPTX, ODT/ODS in navadne besedilne datoteke. Skenirani, zaščiteni, preveliki, stari DOC/XLS in zunanje omejene priloge ostanejo označeni kot neobdelani; starejša objava istega dosjeja je označena kot nadomeščena, če je v bazi že novejša. Poročilo zato ne trdi, da je pokritje popolno. Besedilo vseh berljivih prilog se pregleda za izraze iz profila, največ 20 kandidatnih odlomkov na prilogo pa oceni Gemini Decision 1 (privzeto skupna omejitev 1.000 vprašanj na zagon). Dodatni zadetki in neocenjeni odlomki so vidno označeni za ročni pregled. V Google se pošljeta opis sposobnosti in javni odlomek, ne naziv ali matična številka podjetja. Ta pregled ne potrjuje pogojev za prijavo.

Privzeto se uporabi **trenutni profil podjetja v aplikaciji**; nobena panoga ni vnaprej izbrana. Datoteka `backend/examples/hvac-profile.json` je samo neobvezen testni primer.

Cevovod in zavihek Pretekle oddaje prikažeta znane ponudnike s statusom **Zmagovalec**, **Ni bil izbran** ali **Prijavljen – izid ni potrjen** ter virom. Zmagovalce določa obvestilo o oddaji. Dodatne strukturirane zapisnike je mogoče uvoziti z `manage.py import_participants zapisniki.json`; vsak zapis mora vsebovati `award_id` (točen sklop) in `participants`, kjer so polja `name`, `registration_number`, `outcome` (`not_selected` ali `unknown`) in `source_url` (javni zapisnik na e-JN/PJN). Uvoz ohrani prej vnesene ponudnike; ponovni uvoz oddaj jih ne izbriše. Nepotrjen izid se ne pretvori v poraz. Uvoženi vir je označen in ni avtomatično vsebinsko verificiran.

Samodejni zajem javnega odpiranja e-JN še ni povezan: preverjanje neposrednega dostopa je vrnilo HTTP 407. Zato se za sklope brez dodatnega zapisnika jasno izpiše, da imena drugih ponudnikov še niso pridobljena. Arhivski ukaz je ločen od gumba »Osveži razpise« in njegove dnevne kvote; med objavami privzeto počaka 0,5 sekunde.

V podrobnostih razpisa na zavihku **Pregled** razdelek **Priložnost za dobavo ali podizvajanje** prikaže že shranjene ugotovitve za trenutni profil in dokumente. Z gumbom **Preveri priloge** lahko pregledate tudi posamezen razpis z že uvoženimi dokumenti. Vmesnik prikaže citat, povezavo do datoteke in znane ponudnike iz podobnih oddaj, kadar so na voljo. Povezava do PDF-ja odpre navedeno stran, Office datoteka pa se prenese.

Vir: **Javne informacije Slovenije – portal javnih naročil**. [Dokumentacija API in pogoji ponovne uporabe](https://podatki.gov.si/dataset/api-pjn).

### Dokumenti in AI

Podprti so besedilni PDF-ji in ZIP arhivi: največ 10 MB na datoteko, 30 članov oziroma 20 MB razpakirane vsebine in 150 strani na PDF. Skeni, zaščiteni dokumenti in nepodprti formati ostanejo označeni za dodaten pregled. Izluščeno besedilo še ne pomeni analize pogojev.

Za živo analizo kopirajte `.env.example` v `.env` in nastavite `OPENROUTER_API_KEY` (privzeti model `openai/gpt-6-luna`, spremenljiv z `OPENROUTER_MODEL`) ali `OPENAI_API_KEY` in `OPENAI_MODEL`, nato znova zaženite backend. Če sta nastavljena oba, ima prednost OpenRouter; zahteve gredo samo k ponudnikom s strukturiranim izhodom, ki ne zbirajo podatkov za učenje. Citati v odgovorih se dobesedno preverijo proti strani dokumenta, sicer je prikazan demo odgovor. Ključ ostane na strežniku; `.env` ni v Gitu. Model prejme ustrezne podatke profila in dokumentacije. Brez ključa se uporabljajo pripravljene demo analize in označeni demo odgovori; pogojev resničnih dokumentov aplikacija ne izmišljuje.

Za AI presojo, ali se **predmet** razpisa ujema s podjetjem, nastavite še `GEMINI_API_KEY` in znova zaženite backend. Gemini Decision 1 prejme dejavnost, opis, področja, ključne besede in tehnologije profila ter naslov, predmet, vrsto in CPV razpisa; ne prejme naziva podjetja, matične številke, naslova, referenc ali dokumentacije. Brez ključa ostanejo pravila. Vmesnik pri vsaki oceni pokaže uporabljeni način. AI ocena ne potrjuje obveznih pogojev in ni verjetnost uspeha. Pri brezplačni ravni Gemini API lahko Google poslano vsebino uporabi za izboljšave.

Gemini ocene se izračunajo v paketih in shranijo; sprememba profila ali razpisa jih osveži. Ob nedosegljivosti se za 15 minut uporabi označena ocena po pravilih. Zajem objav ostane časovno omejen, zato obvestila o povsem novih objavah najprej uporabijo pravila; seznam razpisov ob odprtju izračuna AI ujemanje. Simulacije razvojnih načrtov ostanejo izračun po pravilih.

### Primerjava vsebinskega ujemanja

Orodje za razvijalce izmeri, kako dobro trije pristopi presodijo vsebinsko primernost razpisa: sedanja pravila s ključnimi besedami, LLM (OpenRouter oziroma OpenAI) in [Gemini Decisions API](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/). Aplikacije ne spreminja.

1. `backend/manage.py relevance_eval export` zapiše `backend/eval/relevance_labels.csv`: vsak resničen razpis iz baze v paru s štirimi **izmišljenimi** profili (IT, ceste, tiskarna, optična omrežja). Ponovni izvoz po novem zajemu doda nove vrstice in ohrani oznake.
2. V stolpec `label` vpišite `primeren` (jedrna dejavnost, podjetje bi naročilo izvedlo samo), `delno` (sorodno področje, potreben partner) ali `neprimeren`; dovolj so tudi `p`, `d`, `n`. Presojate samo predmet naročila, ne pogojev, vrednosti ali roka. Oznake naj določi človek, ne model.
3. `backend/manage.py relevance_eval run --show-errors` izpiše točnost, makro F1, natančnost in priklic za »primeren«, hude napake (primeren ↔ neprimeren) ter Brierjevo oceno za verjetnostne napovedi. `--out tmp/rezultati.json` shrani napovedi po vrsticah.

LLM se uporabi, če je nastavljen `OPENROUTER_API_KEY` ali `OPENAI_API_KEY`. Gemini zahteva `GEMINI_API_KEY` (model `GEMINI_DECISION_MODEL`, privzeto `gemini-decision-1`). Brez ključa se pristop preskoči. Ponudnikom se pošiljajo samo izmišljeni profili in javni metapodatki razpisov, nikoli shranjeni profil podjetja. Pri brezplačni ravni Gemini API lahko Google vsebino uporabi za izboljšave.

### Podobna pretekla naročila

Zavihek **Pretekle oddaje** (samo pri resničnih razpisih) poišče podobne sklope v uvoženih obvestilih o oddaji. Pokaže, kdo je bil izbran, koliko ponudb je naročnik prejel, pogodbeno in ocenjeno vrednost ter najnižjo in najvišjo dopustno ponudbo. Doda še mediane in najpogostejše izbrane ponudnike. Imen neuspešnih ponudnikov obvestila o oddaji ne objavljajo.

Administracija v razdelku **Pretekle oddaje** prikazuje število shranjenih obvestil, sklopov in oddanih sklopov, razpon datumov objave, zadnji uvoz ali posodobitev ter razrez po mesecih objave. Pregled se osvežuje vsakih 5 sekund, tudi med dopolnjevanjem starejših obdobij. Statistika opisuje shranjeno zbirko in ne potrjuje popolnosti zajema obdobja.

Oddaje se prenašajo neposredno s Portala javnih naročil (`obrazecGet` obvestil v fazi »Rezultat«: sklopi, izbrani ponudniki z matično številko, število ponudb, izbrana ter najnižja in najvišja dopustna vrednost):

- vsako obvestilo o oddaji, ki ga zajem prenese (dnevni zagon, `sync_pjn`, uvoz po URL-ju), se zapiše tudi med pretekle oddaje;
- dnevni zagon (`enqueue_pipeline --watch`) nato prenese še manjkajoča obvestila o oddaji od najnovejše shranjene oddaje (2 dni prekrivanja) do danes;
- starejše obdobje zapolnite ročno:

```bash
.venv/bin/python backend/manage.py sync_past_awards --from 2026-01-01 --to 2026-06-24
```

Ukaz brez `--from` nadaljuje od najnovejše oddaje. Že shranjena obvestila preskoči, `--max-notices` omeji zagon, `--delay` (privzeto 0,3 s) določa premor med zahtevki.

Začetna zbirka je v repozitoriju (`backend/source_data/past_awards/`, licenca CC BY 4.0) in se ob prvem zagonu (`seed_demo`, v Dockerju samodejno) ali prvem odprtju zavihka naloži v prazno tabelo. Sestavljena je iz izvozov Apify strgalnika [`publicmoney/enarocanje-slovenia-scraper`](https://apify.com/publicmoney/enarocanje-slovenia-scraper) (`phase: RESULT`, `fetchDetails: true`). Takšen izvoz še vedno lahko uvozite in z njim osvežite zbirko za Git:

```bash
.venv/bin/python backend/manage.py import_past_awards pot/do/izvoza.json --write-bundle
```

Preslikava PJN je bila 12. 11. 2026 preverjena na 108 obvestilih iz izvoza strgalnika in se z njim ujema v vseh poljih. Edina razlika je CPV sklopa: strgalnik vzame samo dodatne kode, PJN preslikava pa glavno in dodatne. Ponovni uvoz posodobi obstoječe zapise. Kandidate izbere besedilna podobnost naslova in opisa skupaj s kodo CPV. Če je nastavljen `GEMINI_API_KEY`, kandidate (največ 40) razvrsti Gemini Decisions API: ostanejo tisti z verjetnostjo podobnosti vsaj 0,5. Rezultat se shrani in ponovno uporabi, dokler se razpis ali zbirka ne spremenita. Brez ključa ali ob napaki se prikaže besedilno ujemanje z oznako. Gemini prejme samo javne podatke razpisa in preteklih oddaj, profila podjetja ne. Vir: Portal javnih naročil, CC BY 4.0.

### Podjetja, partnerji in demo podatki

AJPES/OPSI povezava uporablja javni nabor PRS brez API ključa. Predizpolni samo **naziv, matično številko in naslov**. Rezultati se hranijo 24 ur. [Vir in licenca CC BY 4.0](https://podatki.gov.si/dataset/poslovni-register-slovenije).

Začetni nabor vsebuje šest izmišljenih razpisov, en resničen arhivski zapis in pet demo PDF-jev, vključno s popravljeno različico satelitskega razpisa. Datumi demo objav se določijo ob pripravi oziroma ponastavitvi; arhivski datumi ostanejo izvorni. **Demo oznake so vidne tudi na karticah in v prihajajočih rokih.** Arhivski zapis ni aktualna priložnost.

Partnerji prispevajo samo podatke s podprtimi dokazili. Uporabniška potrditev ni neodvisno preverjanje. Skupni potencial zahteva pregled dovoljenega načina skupne prijave. Razvojni načrti primerjajo predpostavke s trenutnimi pogoji in ne spreminjajo profila. Demo in resnični podatki se pri teh primerjavah ne mešajo.

## Struktura projekta

Za spletno namestitev uporabite [`compose.coolify.yaml`](compose.coolify.yaml):
[navodila za Coolify, domeno in pipeline na istem strežniku](docs/coolify.md).

Ločeni strežnik za prenos, skupno indeksiranje prilog in opravila v PostgreSQL:
[namestitev in uporaba](docs/pipeline-server.md).

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
| `backend/tenders/past_awards.py`, `frontend/src/PastAwards.tsx` | Uvoz obvestil o oddaji in podobna pretekla naročila |
| `backend/tenders/relevance_eval.py`, `backend/eval/` | Primerjava pristopov za vsebinsko ujemanje na označenem naboru |
| `backend/demo_documents/`, `source_data/` | Demo dokumentacija, šifranti in zbirka preteklih oddaj |
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

## Dnevnik sprememb

- **Git log je dnevnik sprememb.** Vsak commit ima poleg naslova telo: zakaj je bila sprememba narejena, katere odločitve so bile sprejete, migracije in konfiguracija, kaj je preverjeno in kaj ne ter kaj ostaja odprto. Predloga je v `.gitmessage`; vključite jo z `git config commit.template .gitmessage`.
- Spremembe API-ja se zapišejo tudi v CONTRACT.md.

Zgodovino z razlagami pregledate z `git log` (brez `--oneline`).

## Meje prototipa

Gre za lokalno aplikacijo za enega uporabnika. Vsebinsko ujemanje je razložljiva hevristika, ne verjetnost uspeha. Neznani pogoji ostanejo neznani; presoja zajema samo obdelano dokumentacijo. Produkcijska prijava in izolacija uporabnikov, OCR, pošiljanje e-pošte ter celovit zajem vseh objav niso vključeni.


## Pregled pripravljene prijave z AI

V podrobnostih razpisa odprite **Pregled prijave**. Naložite ZIP ali več dokumentov ponudbe, po potrebi tudi uradno razpisno dokumentacijo, ki še ni shranjena. Skupna omejitev je 10 MB. Razpisni viri in dokumenti ponudnika so ločeni.

AI iz dokumentacije in shranjenih pojasnil naročnika izlušči kontrolni seznam zahtev: obrazci, priloge, dokazila, tehnični elementi, zavarovanja in navodila. Nato zahteve primerja s prijavo. Rezultat pokaže **pokrito z dokazom / delno pokrito / manjka / ročno preveri / ni relevantno**, dokument, stran, citat in naslednji korak. Citati se preverijo proti dejanskemu besedilu; odsotnost dokaza ob neberljivih prilogah ostane neznana.

Potreben je `OPENROUTER_API_KEY` iz `.env`. Ločena nastavitev `SUBMISSION_REVIEW_MODEL` je privzeto `openai/gpt-6.1-terra`. Po spremembi nastavitev znova zaženite backend. Pregled opravi dva klica modela in lahko traja do tri minute. Napaka povezave ne vrne izmišljenega poročila.

Podprti so PDF, DOCX, XLSX, PPTX, ODT, ODS, TXT, CSV, XML in JSON. ZIP ima omejitve: 100 datotek, 10 MB na datoteko in 50 MB razpakirane vsebine. Njegove poti se ne uporabljajo za zapis datotek. Enake datoteke se upoštevajo enkrat; macOS sistemske datoteke se prezrejo. Omejitev besedila je 220.000 znakov za vsako stran primerjave; presežek vrne napako.

Če ZIP vsebuje različne prijave z istoimenskimi dokumenti, izberite **Mapa prijave v ZIP-u**. Pri uporabnikovem vzorcu izberite `PDF` ali `PDF/BREZ`; upoštevajo se samo datoteke neposredno v izbrani mapi. Tako se dokazila različnih različic ne združijo v eno prijavo.

Skeni in neberljive strani so označeni za OCR ali ročni pregled. Funkcija ne preverja kriptografskih podpisov, žigov, veljavnosti dokazil ali dejanske oddaje. Seznam zahtev in ugotovitve so predhodna analiza razpoložljivih virov; popolnost in pravno dopustnost preveri človek.

Naložene datoteke se obdelajo začasno in po branju odstranijo; njihovo besedilo se pošlje modelu prek OpenRouterja. Prijava se ne zapiše med razpisne vire. Poročilo je v pomnilniku zavihka; pred odhodom ga prenesite kot JSON. `PDF.zip` je uporabnikov vzorec in se ne dodaja v Git.

API: `POST /api/tenders/<id>/submission-review`, multipart polji `submission_files` in neobvezno `source_files`, ter besedilno polje `submission_folder`. Odziv vsebuje model, različico razpisa, čas pregleda, ugotovitve, števce, dokaze in seznam nepreverjenih dokumentov. Funkcija ne potrebuje nove migracije.
