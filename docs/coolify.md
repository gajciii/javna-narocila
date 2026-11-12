# Spletna aplikacija na Coolify

`compose.coolify.yaml` zažene dve storitvi: React/Nginx (`frontend`) in Django/Gunicorn
(`backend`). PostgreSQL, zasebna shramba dokumentacije, delavec in scheduler ostanejo na
`it-server-pc`. Coolify na eni HTTPS domeni posreduje promet v `frontend`; Nginx zahteve
`/api/` posreduje v zasebni `backend:8000`. Ta Compose ne ustvarja druge baze ali drugega pipelinea.

## 1. Zasebna povezava

Strežnik, na katerem Coolify izvaja vsebnike, mora biti povezan v isti Tailscale kot
`it-server-pc`. Pravila tailneta morajo dovoljevati dostop do:

- `100.64.0.7:55432` — PostgreSQL;
- `100.64.0.7:9002` — zasebna shramba S3.

Povezava mora delovati tudi iz Docker vsebnika. Uporabite zasebni IP, če MagicDNS v
Dockerju ne razreši imena `it-server-pc`. Obstoječih vrat baze in shrambe ne odpirajte v
javni internet. Za preverjanje v Coolify terminalu storitve `backend` zaženite:

```bash
python manage.py check_pipeline_connection
```

Ukaz prebere samo stanje baze in vedra. Ne izpisuje povezovalnih nizov, ključev ali gesel.
Če se backend ne zažene zaradi nedosegljive baze, najprej uredite povezavo Tailscale na
Coolify strežniku; migracije in healthcheck brez te povezave ne morejo uspeti.

## 2. Nastavitev vira in domene

1. Spremembe s tem Compose in aplikacijo morajo biti v izbrani Git veji.
2. V Coolify ustvarite aplikacijo iz repozitorija in izberite **Docker Compose** kot build pack.
3. Nastavite **Base Directory** na `/` in **Docker Compose Location** na `/compose.coolify.yaml`.
4. Dodelite HTTPS domeno samo storitvi **frontend**, z notranjimi vrati **80**.
   Primer vrednosti v Coolify Domains: `https://razpizi.example.com:80`.
   `:80` označuje ciljna vrata vsebnika; obiskovalci uporabljajo običajen HTTPS naslov.
5. DNS domene usmerite na javni naslov Coolify strežnika in omogočite HTTPS v Coolify.

`backend` ne potrebuje javne domene ali objavljenih vrat. Compose ne objavlja nobenih vrat
na gostitelju; javni promet prevzame Coolifyjev proxy. Ne podvajajte tega s port mappingom.

## 3. Okoljske spremenljivke

V **Environment Variables** vnesite vrednosti iz `.env.coolify.example`.

| Spremenljivka | Vrednost |
| --- | --- |
| `PUBLIC_APP_URL` | Npr. `https://razpizi.example.com`, brez poti in brez notranjega `:80`. |
| `DJANGO_SECRET_KEY` | Dolg, naključen ključ za to spletno namestitev. |
| `DATABASE_URL` | Povezava do obstoječe baze, npr. `postgresql://razpizi:<URL-kodirano geslo>@100.64.0.7:55432/razpizi`. |
| `PIPELINE_S3_ENDPOINT` | `http://100.64.0.7:9002`. |
| `PIPELINE_S3_BUCKET` | `razpizi-documents`. |
| `PIPELINE_S3_ACCESS_KEY` | Obstoječi ključ zasebne shrambe. |
| `PIPELINE_S3_SECRET_KEY` | Obstoječe geslo zasebne shrambe. |

Zasebne povezovalne vrednosti so v lokalni `.env` oziroma `.env.pipeline.client` in na
pipeline strežniku v zasebni `.env.pipeline`. Kopirajte jih neposredno v nastavitve Coolify;
ne dodajajte jih v repozitorij. `.env.coolify` in njegove zasebne različice so izključene iz Gita.

AI ključe dodajte po potrebi. Za enako obnašanje uporabite isti `GEMINI_DECISION_MODEL` in
ključ Gemini kot na pipeline strežniku. Ključi ostanejo v backendu; Vite jih ne prejme med gradnjo.

`PUBLIC_APP_URL` določi dovoljeno ime gostitelja in zaupanja vreden izvor za prijavo ter
spremembe podatkov. Če domeno zamenjate, spremenite tudi to vrednost in ponovno namestite.
Ta namestitev pričakuje aplikacijo v korenu domene, ne podpot `/app`.

## 4. Prijava in delovanje

Spletna namestitev privzeto zahteva prijavo za celoten API aplikacije, ker trenutno vsi
uporabniki uporabljajo isti profil podjetja. Obiskovalec se preusmeri na prijavo v administracijo.
Uporabite obstoječi račun `admin` iz skupne PostgreSQL baze in njegovo geslo. Po prijavi
izberite **Razpisi** za običajni vmesnik ali ostanite v administratorskem portalu.

Za povsem novo bazo račun ustvarite v terminalu storitve `backend`:

```bash
python manage.py createsuperuser
```

HTTPS je zaključen na Coolify proxyju. Nginx ohrani pravilen `X-Forwarded-Proto`, Django
pa uporablja varne sejne/CSRF piškotke in preverja CSRF tudi za običajne spremembe profila.
Backend mora ostati v zasebnem Docker omrežju; nastavitev zaupanja proxyju temelji na tem.

Ob zagonu backend izvede migracije in zažene Gunicorn. Podatkov obstoječe baze ne ponastavlja.
Ročni zagoni iz administracije se izvajajo na `it-server-pc`; v Coolify ne dodajajte workerja
ali schedulerja iz `compose.pipeline.yaml`.

## 5. Preverjanje namestitve

- `https://<domena>/healthz` preveri Nginx;
- `https://<domena>/api/health` preveri povezavo do baze brez prijave, uvoza ali klicev AI;
- `https://<domena>/#/administracija` odpre prijavo in pregled pipelinea;
- `python manage.py check_pipeline_connection` v backend vsebniku preveri PostgreSQL in S3.

Compose že vsebuje oba healthchecka. Prvi zagon lahko traja dlje zaradi migracij. Volumen
`web-media` ohrani lokalne delovne datoteke spletne aplikacije; izvorni dokumenti pipelinea
ostanejo v obstoječi S3 shrambi na ločenem strežniku.

Referenca: [Coolify Docker Compose](https://coolify.io/docs/applications/builds/docker-compose).
