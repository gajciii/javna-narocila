# E-poštna obvestila

E-pošto vključite v **Moj račun → E-poštna obvestila**: shranite naslov prejemnika in vključite pošiljanje. Vsak račun ima svoje nastavitve. Spremembe pogojev, dokumentacije in rokov spremljanih resničnih razpisov se pošiljajo sproti. Nove odprte razpise, ki se vsebinsko ujemajo z aktivnim profilom podjetja in niso skriti, pošljemo v zbirnem pregledu. Privzeto je to dnevno ob 8.00 po slovenskem času; uporabnik lahko izbere tedensko ob ponedeljkih ob 8.00 ali zbirnik izključi. Pregled pošljemo samo, če vsebuje vsaj en nov primeren razpis. Demo dogodki in razvojni predlogi se po e-pošti ne pošiljajo. Prebrano obvestilo v aplikaciji ne ustavi e-pošte.

Pošiljanje je na voljo prek SMTP ali Resend. Ponudnika na strežniku izberete z `EMAIL_PROVIDER=smtp` (privzeto) ali `EMAIL_PROVIDER=resend`. Izbrani način je viden v nastavitvah obvestil. Ob napaki pri Resend ne preklapljamo samodejno na SMTP.

Za Resend nastavite na backendu in mailerju:

```dotenv
EMAIL_PROVIDER=resend
RESEND_API_KEY=
DEFAULT_FROM_EMAIL=RazpIzi <obvestila@example.com>
PUBLIC_APP_URL=https://razpizi.example.com
```

`RESEND_API_KEY` vnesite v okolje strežnika, nikoli v brskalnik ali Git. Pošiljatelj mora uporabljati [domeno, preverjeno v Resend](https://resend.com/docs/dashboard/domains/introduction). Nastavitve `EMAIL_HOST`, vrat in SMTP prijave pri Resend niso potrebne. Prejemnika še vedno shranite in pošiljanje vključite v aplikaciji.

Za SMTP na strežniku nastavite naslednje spremenljivke (predlogi sta `.env.example` in `.env.coolify.example`):

- `PUBLIC_APP_URL`: javni izvor aplikacije, npr. `https://razpizi.example.com`.
- `EMAIL_HOST`, `EMAIL_PORT`: naslov in vrata SMTP strežnika.
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`: podatki za prijavo, če jih SMTP zahteva. Dejanske vrednosti shranite v nastavitve okolja, ne v Git.
- `DEFAULT_FROM_EMAIL`: dovoljen naslov pošiljatelja, npr. `RazpIzi <obvestila@example.com>`.
- `EMAIL_USE_TLS=1`, `EMAIL_USE_SSL=0`: STARTTLS, običajno vrata 587. Za implicitni TLS nastavite `EMAIL_USE_TLS=0`, `EMAIL_USE_SSL=1`, običajno vrata 465. Obe možnosti ne smeta biti vključeni hkrati.

Po namestitvi izvedite `python manage.py migrate --noinput`. `compose.coolify.yaml` in `compose.yaml` vključujeta storitev `mailer`, ki se zažene po zdravem backendu. Po spremembi ponudnika ali nastavitev pošiljanja ponovno zaženite backend in mailer. Če Django teče neposredno na gostitelju, zaženite ločen trajen proces z istim okoljem in bazo:

```sh
python manage.py send_notification_emails --watch
```

Enkraten prehod vrste: `python manage.py send_notification_emails`. Proces preveri vrsto vsakih 15 sekund. Zajem PJN mora delovati posebej: sporočila o spremembah nastanejo ob zaznani spremembi, zbirnik pa izbira razpise, ki so bili na novo shranjeni od prejšnjega pregleda. Primernost izračuna posebej za aktivni profil vsakega računa. Nobena poskusna pošta se ne pošlje samodejno ob shranjevanju nastavitev.

Ob vključitvi ali menjavi naslova začne veljati nov časovni prag: starejša obvestila in razpisi se ne pošiljajo. Ob izklopu ali menjavi prejemnika prekličemo še neposlana sporočila. Sprememba dnevne/tedenske pogostosti prekliče čakajoči zbirnik in ohrani njegov časovni obseg za naslednji pregled. Prenehanje spremljanja ustavi čakajoča sporočila o spremembah tega razpisa. Sporočilo, ki ga je ponudnik že prevzel, ne more biti preklicano.

Obvestila, zbirniki in poskusi pošiljanja so shranjeni v bazi. Za vsako obvestilo obstaja največ en zapis pošiljanja. Pošiljalci se uskladijo z zaklepanjem vrstice v PostgreSQL; lokalni SQLite je namenjen enemu procesu mailerja. Uspešnih zapisov ne pošiljamo ponovno. Neuspešno pošiljanje ponovimo največ petkrat, s presledki 1, 2, 4 in 8 minut. Po petem neuspehu je zapis označen kot `failed`, kar je vidno v nastavitvah obvestil. Po odpravi napake lahko skrbnik izbrane neuspele zapise v `NotificationEmail` ali `TenderDigestEmail` prek Django shell vrne v stanje `pending`, nastavi `attempts=0` in `available_at=timezone.now()`; veljavnost prejemnika in nastavitev se ponovno preveri pred pošiljanjem.

SMTP ne zagotavlja natanko enkratne dostave: ob prekinitvi povezave po prevzemu sporočila ali padcu procesa pred potrditvijo transakcije se lahko ponovljen poskus podvoji. Vsi ponovni poskusi uporabljajo isti `Message-ID`. Pri Resend uporabljamo [API za pošiljanje](https://resend.com/docs/api-reference/emails/send-email) ter trajni `Idempotency-Key` za vsak zapis pošiljanja. Ključ je enak pri vseh ponovnih poskusih, vsebino in pošiljatelja pa shranimo v čakalno vrsto. [Resend hrani ključe 24 ur](https://resend.com/docs/dashboard/emails/idempotency-keys); po tem obdobju podvojitve ob ponovnem poskusu niso izključene. Ob menjavi ponudnika najprej zaključite ali prekličite obstoječa čakajoča sporočila.

Stanje `sent` pomeni, da je ponudnik sporočilo prevzel, ne potrjene dostave v prejemnikov predal. Vsebine napak ponudnika in gesel ne vračamo v API.


V **Moj račun → E-poštna obvestila → Testna obvestila** lahko ročno pošljete test povezave, testni dnevni pregled ali testni tedenski pregled. Dnevni test vsebuje primerne razpise, shranjene v zadnjih 24 urah, tedenski pa v zadnjih 7 dneh; uporablja isti izbor za aktivni profil in iste izključitve kot redni pregled. Predmet pregleda je označen z `[TEST]`. Če ni primernih razpisov ali profila, vseeno pošljemo test s pojasnilom. Testi uporabljajo shranjeni naslov prejemnika oziroma prijavni naslov, zato spremenjeni naslov najprej shranite. Delujejo tudi pri izključenih rednih obvestilih in ne spreminjajo nastavitev, časovnega praga, urnika ali čakalne vrste. Vsako vrsto testa lahko račun pošlje enkrat na minuto. Uspešen odgovor pomeni prevzem pri ponudniku; prejem preverite v svojem predalu, vključno z vsiljeno pošto.
