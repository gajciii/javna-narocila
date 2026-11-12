# E-poštna obvestila

E-pošto vključite v **Obvestila → E-poštna obvestila**: shranite naslov prejemnika in vključite pošiljanje. Nastavitev velja za obstoječo aplikacijo z enim skupnim profilom podjetja. Pošiljajo se prihodnje spremembe pogojev in rokov spremljanih resničnih razpisov. Demo dogodki, novi razpisi in razvojni predlogi se ne pošiljajo. Prebrano obvestilo v aplikaciji ne ustavi e-pošte.

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

Enkraten prehod vrste: `python manage.py send_notification_emails`. Proces preveri vrsto vsakih 15 sekund. Zajem PJN mora delovati posebej: pošta se ustvari šele ob zaznani spremembi, ne neposredno ob objavi na portalu. Nobena poskusna pošta se ne pošlje samodejno ob shranjevanju nastavitev.

Ob vključitvi ali menjavi naslova začne veljati nov časovni prag: starejša obvestila se ne pošiljajo. Ob izklopu ali menjavi prejemnika prekličemo še neposlana sporočila. Prenehanje spremljanja ustavi tudi čakajoča sporočila tega razpisa. Sporočilo, ki ga je ponudnik že prevzel, ne more biti preklicano.

Obvestila in poskusi pošiljanja so shranjeni v bazi. Za vsako obvestilo obstaja največ en zapis pošiljanja. Pošiljalci se uskladijo z zaklepanjem vrstice v PostgreSQL; lokalni SQLite je namenjen enemu procesu mailerja. Uspešnih zapisov ne pošiljamo ponovno. Neuspešno pošiljanje ponovimo največ petkrat, s presledki 1, 2, 4 in 8 minut. Po petem neuspehu je zapis označen kot `failed`, kar je vidno v nastavitvah obvestil. Po odpravi napake lahko skrbnik izbrane neuspele zapise prek Django shell vrne v stanje `pending`, nastavi `attempts=0` in `available_at=timezone.now()`; prejemnik in časovni prag se ponovno preverita pred pošiljanjem.

SMTP ne zagotavlja natanko enkratne dostave: ob prekinitvi povezave po prevzemu sporočila ali padcu procesa pred potrditvijo transakcije se lahko ponovljen poskus podvoji. Vsi ponovni poskusi uporabljajo isti `Message-ID`. Pri Resend uporabljamo [API za pošiljanje](https://resend.com/docs/api-reference/emails/send-email) ter trajni `Idempotency-Key` za vsak zapis pošiljanja. Ključ je enak pri vseh ponovnih poskusih, vsebino in pošiljatelja pa shranimo v čakalno vrsto. [Resend hrani ključe 24 ur](https://resend.com/docs/dashboard/emails/idempotency-keys); po tem obdobju podvojitve ob ponovnem poskusu niso izključene. Ob menjavi ponudnika najprej zaključite ali prekličite obstoječa čakajoča sporočila.

Stanje `sent` pomeni, da je ponudnik sporočilo prevzel, ne potrjene dostave v prejemnikov predal. Vsebine napak ponudnika in gesel ne vračamo v API.
