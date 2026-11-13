# Uporabniški računi

Registracija je na `#/registracija`, prijava na `#/prijava`. Nov račun uporablja e-poštni naslov kot uporabniško ime. Obstoječi skrbniki se lahko prijavijo tudi z dosedanjim uporabniškim imenom. Registracija uporabnika takoj prijavi, odjava pa prekliče sejo.

Pred zagonom posodobljene aplikacije izvedite migracije:

```sh
.venv/bin/python backend/manage.py migrate
```

Prijava je privzeto obvezna za podatke aplikacije. Domača stran in obrazca za prijavo/registracijo so javni. `ACCOUNT_REQUIRE_LOGIN=0` ohrani star anonimni demo za razvojne teste; na javni namestitvi naj ostane privzeta vrednost `1`. `HOSTED_REQUIRE_LOGIN=1` prav tako zahteva prijavo in dovoljuje tudi običajne registrirane uporabnike. Administracijski API še vedno zahteva skrbniški račun.

Vsak uporabnik ima svoja podjetja, aktivno podjetje, shranjena iskanja, spremljanje razpisov, prebrana obvestila in nastavitve e-pošte. Partnerji, razvojni načrti in ESPD so ločeni po uporabniku in identiteti podjetja; dva uporabnika lahko neodvisno shranita isto podjetje. Javne objave in razpisna dokumentacija ostajajo skupni podatki. Globalni demo dogodki, ponastavitev in uvoz so dostopni skrbnikom.

Dosedanji podatki brez lastnika ostanejo ohranjeni. Prvi obstoječi skrbnik, ki se prijavi in še nima svojih podjetij, prevzame stari skupni profil, iskanja, partnerje, načrte, ESPD in nastavitve e-pošte. Registrirani uporabniki teh podatkov ne prevzamejo. Izvoz za prenos javne baze izpusti zasebne podatke računov ter prijavne podatke.

Uporabljene so seje Django, preverjanje moči gesel, zaščita CSRF ter omejitev neuspešnih prijav in registracij. V HTTPS namestitvi uporabljajte obstoječe nastavitve `SESSION_COOKIE_SECURE=1`, `CSRF_COOKIE_SECURE=1` in pravilni `PUBLIC_APP_URL`. Omejitve poskusov uporabljajo Django cache; pri več procesih nastavite skupni cache, da omejitev velja za vse procese.

Preverjanje računov in obstoječega demo vedenja na ločeni testni bazi:

```sh
ACCOUNT_REQUIRE_LOGIN=0 DATABASE_URL='' PIPELINE_REMOTE=0 PIPELINE_S3_ENDPOINT='' OPENAI_API_KEY='' OPENROUTER_API_KEY='' GEMINI_API_KEY='' .venv/bin/python backend/manage.py test tenders.test_accounts tenders.test_multiple_companies tenders.tests tenders.test_partners tenders.test_espd tenders.test_improvements tenders.test_email_notifications tenders.test_database_export tenders.test_hosted tenders.test_pipeline_admin
```

Testi računov posebej vključijo obvezno prijavo in preverjanje CSRF tudi ob anonimnem demo načinu drugih testov.
