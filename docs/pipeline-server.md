# Ločeni strežnik za indeksiranje dokumentacije

Spletni Django odda opravilo v PostgreSQL in takoj odgovori z HTTP 202. Delavec na drugem
strežniku prenese dokumentacijo, shrani izvirnike v zasebno S3 shrambo in zgradi skupni
indeks. Pregled za podjetje uporablja ta indeks in izbrane odlomke pošlje Gemini Decision 1.
Spletni vmesnik med obdelavo preverja stanje vsake štiri sekunde.

Uredljiva [skica arhitekture v draw.io](architecture.drawio) vsebuje namestitev in tok obdelave.

## Podatki in indeks

- `IndexedContent`: enkratno izluščeno besedilo, identificirano s SHA-256 in različico ekstraktorja.
- `DocumentChunk`: izvorni odlomki do 1.800 znakov z lokacijo in 180 znaki prekrivanja.
  PostgreSQL `tsvector` in GIN indeks omogočata iskanje brez prebiranja vseh dokumentov.
  Izvirni citat ostane nespremenjen; za iskanje uporabimo normalizirano besedilo.
  Iskanje uporablja predpone izrazov profila (enako začetno logiko kot prejšnji pipeline),
  konfiguracijo `simple` in omejen izbor 40 odlomkov. To še ni semantično vektorsko iskanje
  ali popolna slovenska lematizacija; sopomenke je treba navesti v profilu.
- `PipelineJob`: ločena globalna opravila `index` in opravila `assess` za posnetek profila.
  Sprememba profila uporabi obstoječi indeks. Nova različica razpisa/dokumentov spremeni ključ opravila.
  Delavci prevzamejo opravila s `SELECT FOR UPDATE SKIP LOCKED`. Najem se obnavlja vsakih
  30 sekund; po petih minutah brez obnove ga lahko prevzame drug delavec. Napake se ponovijo
  največ trikrat z odmikom. Rezultat starega najema ne more prepisati novega.

Veliki prenosi in člani ZIP se kopirajo po 1 MB na disk. Privzeta omejitev prenosa je 8 GiB,
skupne razpakirane vsebine 32 GiB in 5.000 članov, globina gnezdenih arhivov največ tri nivoje.
Obdelava posameznega dokumenta je omejena na 512 MiB in 10.000 strani PDF. Office XML ima
dodatne omejitve. Neberljivi, zaščiteni in preveliki dokumenti ostanejo označeni za ročni pregled;
OCR ni dodan. Prekinjeno opravilo lahko nadaljuje iz trajne vrste; prekinjeni HTTP prenos
se začne znova (HTTP Range nadaljevanje še ni implementirano).

## Namestitev

Na strežnik kopirajte `backend/` (brez lokalne baze, medijev in poročil) in `compose.pipeline.yaml`.
Pripravite zasebno datoteko `.env.pipeline`, pravice `600`, z naslednjimi vrednostmi:

```dotenv
PIPELINE_BIND_IP=<zasebni ali Tailscale IP strežnika>
POSTGRES_PASSWORD=<novo dolgo naključno geslo>
PIPELINE_S3_ACCESS_KEY=<nov ključ shrambe>
PIPELINE_S3_SECRET_KEY=<novo dolgo naključno geslo>
GEMINI_API_KEY=<obstoječi ključ Gemini>
GEMINI_DECISION_MODEL=gemini-decision-1
```

Ne dodajajte datoteke z gesli v Git. Vrata baze 55432 in shrambe 9002 so vezana samo na
navedeni zasebni IP. S3 vedro je zasebno; brskalnik do dokumentov dostopa prek aplikacije.
Dockerjeve storitve se samodejno ponovno zaženejo po ponovnem zagonu strežnika.

```bash
docker compose --env-file .env.pipeline -f compose.pipeline.yaml up -d postgres storage
docker compose --env-file .env.pipeline -f compose.pipeline.yaml build worker
docker compose --env-file .env.pipeline -f compose.pipeline.yaml run --rm worker python manage.py migrate --noinput
docker compose --env-file .env.pipeline -f compose.pipeline.yaml run --rm worker python manage.py pipeline_storage
```

Spletni aplikaciji v `.env` nastavite skupno povezavo in shrambo:

```dotenv
DATABASE_URL=postgresql://razpizi:<URL-kodirano geslo>@<zasebni IP>:55432/razpizi
PIPELINE_REMOTE=1
PIPELINE_S3_ENDPOINT=http://<zasebni IP>:9002
PIPELINE_S3_BUCKET=razpizi-documents
PIPELINE_S3_ACCESS_KEY=<isti ključ shrambe>
PIPELINE_S3_SECRET_KEY=<isto geslo shrambe>
```

Pri selitvi obstoječe aplikacije najprej ustavite spletni proces, varnostno kopirajte SQLite
in izvozite `manage.py dumpdata tenders`. Izvoz z `loaddata` naložite v migrirano, prazno
PostgreSQL bazo. Zatem z računalnika, ki ima dostop do starih lokalnih datotek, zaženite
`manage.py pipeline_storage --migrate-files`; ta prenese datoteke v S3 in popravi reference.
Šele nato preklopite aplikacijo in zaženite delavca:

```bash
docker compose --env-file .env.pipeline -f compose.pipeline.yaml up -d worker
```

Za PostgreSQL in objekte uredite varnostne kopije. SQLite po selitvi ohranite kot izhodiščno
kopijo; nove spremembe se zapisujejo samo v PostgreSQL.

## Uporaba in nadzor

```bash
# Obstoječi razpisi, brez novega zajema s PJN:
python manage.py enqueue_pipeline --existing
# Zajem metapodatkov iz izbranega meseca in naročilo indeksiranja:
python manage.py enqueue_pipeline --period 2026-11
# Dnevni pregled novih objav trenutnega meseca:
docker compose --env-file .env.pipeline -f compose.pipeline.yaml --profile scheduled up -d scheduler
# Stanje in dnevnik delavca:
docker compose --env-file .env.pipeline -f compose.pipeline.yaml ps
docker compose --env-file .env.pipeline -f compose.pipeline.yaml logs --tail=50 worker
```

Scheduler preverja vrsto ročnih zahtev vsake tri sekunde in dnevni urnik hrani v PostgreSQL.
V prazni namestitvi opravi prvi pregled ob zagonu, nato vsakih 24 ur. Pri nadgradnji obstoječe
vrste je prvi novi samodejni pregled predviden čez 24 ur; ročni zagon je na voljo takoj.
Odprtega meseca ne označuje kot popoln arhiv. Zagon ob koncu/prehodu meseca za prejšnji mesec izvedite tudi z `--period`.
Ne ocenjuje samodejno vseh podjetij; presojo profila sproži gumb »Preveri priloge«.
`scan_november` ostaja za stari lokalni način in pri `PIPELINE_REMOTE=1` usmeri na novo vrsto.

## Administratorski portal

V aplikaciji odprite **Administracija**, naslov `http://localhost:5174/#/administracija`.
Portal ima ločeno prijavo za aktivne Django uporabnike z `is_staff=True`; API preverja
pravice tudi za branje. Prijava, odjava in vse spremembe zahtevajo CSRF žeton.
Za novo namestitev račun ustvarite v istem okolju/bazi z `python manage.py createsuperuser`.
Obstoječa namestitev ima račun `admin`; geslo je bilo podano prek varnega vnosa in ni v kodi.
Za spletni backend nastavite lasten `DJANGO_SECRET_KEY`. Pri HTTPS nastavite tudi
`SESSION_COOKIE_SECURE=1` in pravilne `DJANGO_CSRF_TRUSTED_ORIGINS`.

Portal prikazuje:

- vrsto opravil, velikost indeksa in zadnji odziv delavca ter schedulerja;
- zgodovino dnevnih, ročnih in CLI zagonov ter povezane razpise in njihova trenutna stanja;
- vsa opravila, tudi presoje prilog na zahtevo, z ločenim dnevnikom posameznih poskusov;
- ročni zajem izbranega meseca ali obstoječih razpisov, z omejitvijo števila objav;
- ponovitev neuspešnega opravila, ki se zabeleži kot nov ročni zagon;
- ustavitev in ponovni vklop dnevnega urnika. Že oddana opravila in ročni zagoni se nadaljujejo.

Zagon iz spletnega portala samo ustvari zahtevo in odgovori z HTTP 202; zajem in obdelava
potekata na ločenem strežniku. Zajem metapodatkov in obdelava prilog imata ločeni stanji:
»Zajem zaključen« še ne pomeni, da so obdelane vse priloge. Pregled se osvežuje na pet sekund.
Več zagonov lahko uporablja isto že indeksirano opravilo; v zgodovini so označena kot ponovno uporabljena.

Migracija obstoječa opravila vključi pod »Prejšnja opravila«. Časov začetka in konca starih
zagonov ne ugiba; podroben dnevnik poskusov se beleži od nadgradnje naprej. Opravila in
njihov dnevnik ostanejo shranjeni tudi po ročni ponovitvi ali poteku najema.

Pri spremembi kode ponovno zgradite sliko, izvedite migracije in ponovno ustvarite delavca
ter scheduler. Opravila in izvirniki ostanejo v trajnih volumnih. Začasne datoteke so v
volumnu `scratch`; po trdem izpadu lahko ostanejo začasni imeniki, zato spremljajte prosti disk.

## Trenutna namestitev

Od 12. 11. 2026 celoten pipeline (PostgreSQL, S3, worker, scheduler) teče na Coolify strežniku
`server-1` v skladu `compose.coolify.yaml`; glejte [Coolify navodila](coolify.md).
Prejšnja namestitev na `it-server-pc` (`/home/viptronik/razpizi-pipeline`) je ustavljena;
njeni volumni so ohranjeni kot rezervna kopija. Ta dokument opisuje samostojno namestitev
z `compose.pipeline.yaml` na ločenem strežniku.
