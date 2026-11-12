# Spletna aplikacija na Coolify

`compose.coolify.yaml` zažene celoten sklad na Coolify strežniku (`server-1`):

| Storitev | Namen | Omejitev RAM |
| --- | --- | --- |
| `frontend` | React/Nginx, javna domena | 128 MB |
| `backend` | Django/Gunicorn | 1,5 GB |
| `postgres` | PostgreSQL 17 (`shared_buffers=256MB`) | 1 GB |
| `storage` | zasebna S3 shramba dokumentacije (versitygw) | 512 MB |
| `worker` | prenos in indeksiranje prilog (`cpus: 2`) | 2 GB |
| `scheduler` | dnevni urnik in ročne zahteve iz administracije | 256 MB |

Strežnik nima swapa, zato ima vsaka storitev `mem_limit`. Če worker preseže omejitev, ga
Docker ponovno zažene; opravilo se po poteku najema nadaljuje oziroma ponovi (največ trikrat).
Skupna zgornja meja je ~5,4 GB, običajna poraba ~1,5–2 GB.

Coolify na eni HTTPS domeni posreduje promet v `frontend`; Nginx zahteve `/api/` posreduje
v zasebni `backend:8000`. Baza in shramba sta dosegljivi samo v Docker omrežju aplikacije
in na `127.0.0.1` gostitelja.

## 1. Dostop do baze in shrambe z delovne postaje

Vrata sta objavljena samo na loopback naslovu gostitelja (`127.0.0.1:55432` in `127.0.0.1:9002`).
Za lokalni razvoj ali administracijo uporabite SSH tunel:

```bash
ssh -N -L 55432:127.0.0.1:55432 -L 9002:127.0.0.1:9002 server-1
```

Lokalni `.env` nato uporablja `DATABASE_URL=postgresql://razpizi:<geslo>@127.0.0.1:55432/razpizi`
in `PIPELINE_S3_ENDPOINT=http://127.0.0.1:9002`. Geslo je v Coolify spremenljivki `POSTGRES_PASSWORD`.

## 2. Nastavitev vira in domene

1. Spremembe s tem Compose in aplikacijo morajo biti v izbrani Git veji.
2. V Coolify ustvarite aplikacijo iz repozitorija in izberite **Docker Compose** kot build pack.
3. Nastavite **Base Directory** na `/` in **Docker Compose Location** na `/compose.coolify.yaml`.
4. Dodelite HTTPS domeno samo storitvi **frontend**, z notranjimi vrati **80**.
   Primer vrednosti v Coolify Domains: `https://razpizi.example.com:80`.
5. DNS domene usmerite na javni naslov Coolify strežnika in omogočite HTTPS v Coolify.

Ostale storitve ne potrebujejo javne domene. Ne objavljajte vrat baze ali shrambe na javnem naslovu.

## 3. Okoljske spremenljivke

V **Environment Variables** vnesite vrednosti iz `.env.coolify.example`.

| Spremenljivka | Vrednost |
| --- | --- |
| `PUBLIC_APP_URL` | Npr. `https://razpizi.example.com`, brez poti in brez notranjega `:80`. |
| `DJANGO_SECRET_KEY` | Dolg, naključen ključ za to spletno namestitev. |
| `POSTGRES_PASSWORD` | Geslo baze; samo črke in številke (uporabi se neposredno v URL-ju). |
| `PIPELINE_S3_BUCKET` | `razpizi-documents`. |
| `PIPELINE_S3_ACCESS_KEY` | Ključ zasebne shrambe. |
| `PIPELINE_S3_SECRET_KEY` | Geslo zasebne shrambe. |
| `GEMINI_API_KEY` | Ključ za presojo prilog (worker in backend). |

`DATABASE_URL` in `PIPELINE_S3_ENDPOINT` določa Compose (`postgres:5432`, `http://storage:9000`).
PostgreSQL ob prvem zagonu s praznim volumnom ustvari bazo z `POSTGRES_PASSWORD`; kasnejša
sprememba spremenljivke gesla v obstoječi bazi ne spremeni (uporabite `ALTER ROLE`).

`PUBLIC_APP_URL` določi dovoljeno ime gostitelja in zaupanja vreden izvor za prijavo ter
spremembe podatkov. Če domeno zamenjate, spremenite tudi to vrednost in ponovno namestite.
Ta namestitev pričakuje aplikacijo v korenu domene, ne podpot `/app`.

## 4. Prijava in delovanje

Spletna namestitev privzeto zahteva prijavo za celoten API aplikacije, ker trenutno vsi
uporabniki uporabljajo isti profil podjetja. Obiskovalec se preusmeri na prijavo v administracijo.
Za povsem novo bazo račun ustvarite v terminalu storitve `backend`:

```bash
python manage.py createsuperuser
```

HTTPS je zaključen na Coolify proxyju. Nginx ohrani pravilen `X-Forwarded-Proto`, Django
pa uporablja varne sejne/CSRF piškotke. Backend mora ostati v zasebnem Docker omrežju.

Ob zagonu backend izvede migracije in zažene Gunicorn. Ponovna namestitev ponovno zažene tudi
worker in scheduler; prekinjeno opravilo nadaljuje drug zagon po poteku najema (pet minut).
Podatki so v volumnih `database`, `objects` in `web-media`; `scratch` vsebuje samo začasne datoteke.
Teh volumnov pri ponovni namestitvi ne brišite in zanje uredite varnostne kopije.

## 5. Preverjanje namestitve

- `https://<domena>/healthz` preveri Nginx;
- `https://<domena>/api/health` preveri povezavo do baze brez prijave, uvoza ali klicev AI;
- `https://<domena>/#/administracija` odpre prijavo in pregled pipelinea;
- `python manage.py check_pipeline_connection` v backend vsebniku preveri PostgreSQL in S3.

Referenca: [Coolify Docker Compose](https://coolify.io/docs/applications/builds/docker-compose).
