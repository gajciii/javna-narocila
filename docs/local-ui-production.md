# Lokalni razvoj UI s produkcijsko bazo

Predloga je v [`.env.ui-production.example`](../.env.ui-production.example).
Lokalna React/Vite in Django uporabljata produkcijsko PostgreSQL bazo ter S3 dokumentacijo
prek SSH tunela. Lokalni worker ni potreben; opravila obdeluje produkcijski worker.

**To ni način samo za branje.** Spremembe profila, spremljanja in druge akcije vplivajo na
produkcijo. Tudi nekateri GET zahtevki lahko zapisujejo (npr. `ensure_seed()` v bootstrapu
in osveževanje predlogov pri branju obvestil). `.env` teh zapisov ne prepreči.
Uporabnik PostgreSQL samo s pravico SELECT prepreči zapise, vendar lahko zato nekateri
zasloni vrnejo napako. Za neomejeno preizkušanje akcij uporabite ločeno kopijo baze.

## Kaj potrebuje kolegica

- Dostop do repozitorija in različico kode, združljivo s produkcijsko shemo baze.
- Python 3.10+ (priporočeno 3.12), Node.js 22+, npm in odjemalec SSH.
- Lasten SSH dostop do produkcijskega strežnika: naslov, uporabniško ime in svoj SSH ključ.
  `server-1` je lokalni SSH vzdevek; na njenem računalniku ga je treba nastaviti ali
  v ukazu zamenjati z `uporabnik@naslov-streznika`. Če je strežnik dostopen samo prek
  Tailscale/VPN, potrebuje tudi ta dostop. Tvojega zasebnega SSH ključa ne kopirajte.
- PostgreSQL uporabnika, geslo in ime baze. Trenutna Compose nastavitev uporablja bazo
  `razpizi`; privzeti produkcijski uporabnik je `razpizi`, geslo pa `POSTGRES_PASSWORD`
  iz Coolifyja. Ta račun ima pravice pisanja. Po možnosti naj skrbnik dodeli namenski račun.
- S3 `PIPELINE_S3_ACCESS_KEY`, `PIPELINE_S3_SECRET_KEY` in ime vedra iz Coolifyja
  (privzeto `razpizi-documents`). Za branje dokumentov zadostujejo dovoljenja za branje
  objektov in preverjanje vedra; produkcijskih korenskih ključev ni treba deliti,
  če skrbnik zagotovi namenski dostop.

Gesla in ključe predajte po varnem kanalu. AI ključi, dostop do Coolify vmesnika in
produkcijski `DJANGO_SECRET_KEY` za običajno urejanje UI niso potrebni.
Administracijski zasloni imajo svojo prijavo; zanje potrebuje obstoječ staff račun.

## 1. Priprava okolja

Ukaze izvajajte v korenu repozitorija. **Ne zaganjajte `scripts/setup.sh` ali
`scripts/dev.sh`: obe skripti izvedeta `migrate` in `seed_demo`.** Proti produkciji
prav tako ne izvajajte `flush`, `seed_demo`, demo ponastavitve ali lokalnih migracij.

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
cp -i .env.ui-production.example .env
chmod 600 .env
```

Windows / PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm.cmd --prefix frontend ci
Copy-Item .env.ui-production.example .env -Confirm
```

Če `.env` že obstaja, pred prepisom shranite obstoječe nastavitve. `.env` je v `.gitignore`.
V kopiji dopolnite štiri označene vrednosti: DB uporabnika in geslo ter oba S3 ključa.
Posebne znake v uporabniku/geslu za `DATABASE_URL` kodirajte kot URL, npr. `@` → `%40`,
`#` → `%23`, `%` → `%25`. S3 ključev ne kodirajte.
Preverite tudi ime baze in vedra, če se razlikujeta od privzetih.
Okoljske spremenljivke terminala imajo prednost pred `.env`; odstranite morebitne stare
izvožene vrednosti za bazo, shrambo in AI ključe.

## 2. SSH tunel (terminal 1)

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:55432:127.0.0.1:55432 -L 127.0.0.1:9002:127.0.0.1:9002 server-1
```

Terminal pustite odprt. Tunel pričakuje porte iz `compose.coolify.yaml` na produkcijskem
strežniku. Naslova `postgres` in `storage` iz Coolify Docker omrežja na njenem računalniku
ne delujeta; zato predloga uporablja `127.0.0.1` in posredovana vrata.

## 3. Preverjanje in Django (terminal 2)

macOS / Linux:

```bash
.venv/bin/python backend/manage.py check_pipeline_connection
.venv/bin/python backend/manage.py runserver 127.0.0.1:8001 --noreload
```

Windows / PowerShell:

```powershell
.\.venv\Scripts\python.exe backend/manage.py check_pipeline_connection
.\.venv\Scripts\python.exe backend/manage.py runserver 127.0.0.1:8001 --noreload
```

Preverjanje opravi `SELECT 1` in S3 `HeadBucket`; ne izvaja migracij ali vnosa demo podatkov.
Če Django opozori na manjkajoče migracije, uskladite različico kode s produkcijo;
lokalnih migracij ne izvajajte na produkcijski bazi. Po spremembi Python kode Django
ponovno zaženite (`--noreload` izključi samodejni ponovni zagon).

## 4. Vite (terminal 3)

macOS / Linux:

```bash
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Windows / PowerShell:

```powershell
npm.cmd --prefix frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Odprite **http://127.0.0.1:5174**. Vite že privzeto posreduje `/api` na
`http://127.0.0.1:8001`, zato dodatna frontend `.env` ni potrebna. Spremembe React/CSS
se prikazujejo sproti. Ob naslednjem delu zadoščajo tunel, Django in Vite.

Lokalno ne zaganjajte workerja, schedulerja ali ukazov za sinhronizacijo: uporabljali bi
isto produkcijsko bazo in vrsto opravil. Brez lokalnih AI ključev so nekateri AI odzivi
nadomeščeni z demo odzivi; obstoječi podatki še vedno prihajajo iz produkcijske baze.
