# Lokalni razvoj Reacta in Djanga s PostgreSQL

Docker Compose zažene **lokalni PostgreSQL 17 in zasebno S3 shrambo**.
Django, Vite, worker in scheduler tečejo na računalniku razvijalke.
Baza in shramba imata lastna Docker nosilca; SSH in produkcijski dostop nista potrebna.

Potrebujete Docker z vtičnikom Compose, Python 3.10+ (priporočeno 3.12), Node.js 22+
in npm. Vse ukaze izvajajte v korenu repozitorija.

## 1. Lokalni .env

Predloga [`.env.local.example`](../.env.local.example) se ujema s
[`compose.dev.yaml`](../compose.dev.yaml). Kopirajte jo v **`.env` v korenu**.
Če `.env` že obstaja, najprej shranite obstoječe nastavitve.

macOS / Linux:

```bash
cp -i .env.local.example .env
```

Windows / PowerShell:

```powershell
Copy-Item .env.local.example .env -Confirm
```

Povezava je `postgresql://razpizi:razpizi-local-only@127.0.0.1:5433/razpizi_local`.
Razvojni uporabnik in geslo sta že nastavljena; produkcijskih skrivnosti ne potrebujete.
Terminal naj nima izvoženih produkcijskih spremenljivk, zlasti `DATABASE_URL` in
`PIPELINE_S3_ENDPOINT`: vrednosti okolja imajo prednost pred `.env`.

## 2. Zagon baze

```bash
docker compose -f compose.dev.yaml up -d --wait
```

Baza je dosegljiva samo lokalno na `127.0.0.1:5433`, S3 pa na `127.0.0.1:9003`.
Uporabljata svoj Docker projekt `razpizi-local` ter nosilca
`razpizi-local_database` in `razpizi-local_objects`. Compose ne uporablja produkcijskih
spremenljivk iz `.env`. Obstoječe datoteke Compose ostanejo za svoje načine zagona;
za lokalno bazo vedno uporabite `-f compose.dev.yaml`.

## 3. Prvi zagon aplikacije

Ko ste preverili, da `.env` kaže na **lokalno** bazo, pripravite odvisnosti,
migracije in začetno prazno okolje.

macOS / Linux:

```bash
./scripts/setup.sh
./scripts/dev.sh
```

Windows / PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm.cmd --prefix frontend ci
.\.venv\Scripts\python.exe backend/manage.py migrate --noinput
.\.venv\Scripts\python.exe backend/manage.py init_workspace
.\.venv\Scripts\python.exe backend/manage.py runserver 127.0.0.1:8001
```

Na Windows v drugem terminalu zaženite še Vite:

```powershell
npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Odprite **http://127.0.0.1:5174**. React/CSS se osvežujeta sproti. `dev.sh` Django
zažene z `--noreload`; po spremembi Python kode ga ponovno zaženite. Za samodejno
osveževanje Djanga ga lahko na macOS/Linux namesto `dev.sh` zaženete ločeno:

```bash
.venv/bin/python backend/manage.py runserver 127.0.0.1:8001
```

V drugem terminalu:

```bash
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Migracije in spremembe podatkov v tem okolju vplivajo na lokalno bazo.
Za preverjanje povezave uporabite `http://127.0.0.1:8001/api/health`;
`check_pipeline_connection` preveri bazo in zasebno S3 vedro; najprej ga ustvarite z `pipeline_storage`.

## 4. Naslednji zagon in ustavitev

Ponovno zaženite bazo z `docker compose -f compose.dev.yaml up -d --wait`, nato
Django in Vite. Odvisnosti namestite znova samo ob njihovih spremembah;
po novih migracijah izvedite `manage.py migrate` proti lokalni bazi.

Aplikacijo ustavite s Ctrl+C, bazo pa z:

```bash
docker compose -f compose.dev.yaml down
```

Podatki ostanejo v Docker nosilcu. `down -v` bi izbrisal lokalno bazo.
Za pregled stanja in dnevnikov:

```bash
docker compose -f compose.dev.yaml ps
docker compose -f compose.dev.yaml logs --tail=50 postgres
```

Okolje se začne s prazno bazo; zgornji ukazi pripravijo prazen profil in zbirko resničnih preteklih oddaj.
Produkcijski podatki se ne prenesejo samodejno. Za realistične podatke potrebujete
ločeno anonimizirano kopijo baze in ustrezne dokumente; reference `s3://` iz produkcije
same po sebi ne zagotovijo lokalnih datotek.

## Samostojen lokalni pipeline

Po migracijah enkrat pripravite lokalno vedro:

```bash
.venv/bin/python backend/manage.py pipeline_storage
.venv/bin/python backend/manage.py check_pipeline_connection
```

Django in Vite ostaneta zagnana po zgornjih navodilih. V dodatnem terminalu zaženite:

```bash
./scripts/pipeline-local.sh
```

Skripta zažene worker in scheduler ter ju ob Ctrl+C ustavi skupaj. Pred zagonom
preveri bazo `razpizi_local` na `127.0.0.1:5433` in S3 na `127.0.0.1:9003`;
produkcijske povezave zavrne. `PIPELINE_REMOTE=1` v tej predlogi vklopi ločeno
vrsto opravil **lokalne** namestitve; ne pomeni povezave s produkcijo.

V `http://localhost:5174/#/administracija` lahko sprožite ročni zagon in preverite
odziv workerja ter schedulerja. Dnevni urnik se upravlja v isti administraciji.
Uvožen izvoz ne vsebuje fizičnih prilog iz produkcijskega S3. Obstoječe indeksirano
besedilo in zgodovina sta dostopna; za odpiranje starih datotek potrebujete še
njihov ločen prenos. Novi lokalni prenosi se shranjujejo v lokalni S3.

## Uvoz izvoza iz administracije

Prijavljen administrator lahko v aplikaciji odpre **Administracija → Izvoz podatkovne
baze → Prenesi izvoz baze**. Datoteka `razpizi-data-<datum>.json.gz` vsebuje podatke
aplikacije v Django fixture obliki. Deluje za PostgreSQL in SQLite; ne vključuje
uporabniških računov, gesel, prijavnih sej ali fizičnih datotek dokumentov. Povezave
zgodovine z administratorji (`requested_by`) so v izvozu prazne. Podatki podjetja in
uporabniški vnosi niso anonimizirani; datoteko delite samo z ustreznimi osebami.
To je prenos podatkov za razvoj, ne popolna varnostna kopija PostgreSQL strežnika.

Za uvoz ustavite lokalni Django, preverite lokalni `DATABASE_URL` in uporabite isto
različico aplikacije kot pri izvozu. Najprej pripravite shemo z `migrate`, nato
uvozite datoteko. Na macOS/Linux:

```bash
.venv/bin/python backend/manage.py migrate --noinput
.venv/bin/python backend/manage.py loaddata /pot/do/razpizi-data-20261112-120000.json.gz
```

Na Windows uporabite `.\.venv\Scripts\python.exe` namesto `.venv/bin/python`.
Uvažajte v prazno lokalno bazo (samo migracije, brez `init_workspace`), ker `loaddata`
posodablja enake primarne ključe, dodatnih obstoječih zapisov pa ne odstrani.
Po uvozu Django in Vite zaženite z ločenima ukazoma iz 3. koraka; `dev.sh` ponovno
zažene `init_workspace`, kar je pri kopiji resničnih podatkov običajno nepotrebno.
Za lokalno administratorsko prijavo ustvarite svoj račun z `manage.py createsuperuser`.

Vrednosti v `.env` ostanejo lokalne; predloga uporablja lokalno bazo in lokalno S3 shrambo. V izvozu ohranjene
S3 poti in izvorne lokalne poti dokumentov na drugem računalniku niso samodejno dostopne.
