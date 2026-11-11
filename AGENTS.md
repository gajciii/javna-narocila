# Navodila za AI agente

Ta datoteka velja za vsakega AI agenta (Claude Code, Codex, Cursor, Copilot …), ki dela na tem projektu. Na projektu dela več ljudi in več agentov hkrati, zato mora vsak pustiti sled, iz katere naslednji razume, kaj se je spremenilo in zakaj.

## Pred začetkom dela

1. Preberi [README.md](README.md) (namen, zagon, struktura) in [CONTRACT.md](CONTRACT.md) (API, podatkovni objekti, pravila).
2. Preberi razdelek **Odprte točke in znane omejitve** na dnu te datoteke.
3. Preglej zadnje spremembe s `git log -10` (s telesi commitov, ne samo `--oneline`). Telo commita pove, zakaj je bila sprememba narejena in kaj ni preverjeno.
4. Preveri `git status`. Če je na `origin/main` kaj novega, najprej povleci in pri konfliktih ohrani delo drugih.

## Po vsaki zaključeni spremembi

1. **Napiši commit s telesom** po spodnji predlogi. Git log je dnevnik sprememb projekta, zato ločenega dnevnika ne vodimo.
2. **Posodobi Odprte točke** na dnu te datoteke: dodaj, kar ostaja odprto, in **izbriši** točke, ki si jih rešil. Razdelek ostane kratek in aktualen; to ni zgodovina.
3. Če se spremenijo API, podatkovni objekti ali pravila, posodobi **CONTRACT.md**.
4. Če se spremeni zagon, konfiguracija (`.env`), funkcionalnost za uporabnika ali struktura projekta, posodobi **README.md**.
5. Zaženi preverjanje: `./scripts/check.sh` (Linux/macOS) ali ukaze iz razdelka *Preverjanje* v README.

### Predloga commit sporočila

Naslov in telo sta v angleščini. Telo je obvezno za vsako spremembo kode.

```text
Add pre-filled ESPD draft per tender            <- naslov: velevnik, do ~72 znakov

Why: Users re-type the same company data for     <- zakaj, ne kaj (kaj pove diff)
every tender; ESPD is required for most bids.
Decisions: Exclusion grounds are never answered  <- pomembne izbire in zavrnjene alternative
automatically (sworn declarations).
Migrations/config: 0006_espd_drafts              <- migracije, .env spremenljivke, odvisnosti
Verified: 136 backend tests, production build.   <- kaj je bilo dejansko preverjeno
Not verified: browser print layout.              <- iskreno, kaj ni
Open: ESPD-EDM XML export.                       <- kar ostaja (prenesi tudi v Odprte točke)

Co-Authored-By: ...                              <- po potrebi
```

Vrstice, ki ne veljajo, izpusti. Predloga je tudi v `.gitmessage`; z `git config commit.template .gitmessage` jo git ponudi ob vsakem `git commit`.

## Pravila projekta

- **Besedila v vmesniku so v slovenščini.** Koda, identifikatorji in commit sporočila so v angleščini.
- **AI mora biti utemeljen z viri.** Trditve o pogojih morajo imeti dokument, stran in dobeseden citat, ki ga strežnik preveri. Če preverjanje ne uspe, se prikaže označen demo odgovor. Ne ohlapnimo preverjanja samo zato, da AI odgovarja pogosteje.
- **Izjav ne izpolnjujemo namesto uporabnika.** To velja za razloge za izključitev v ESPD, potrditve referenc in podobne izjave pod odgovornostjo.
- **Demo in resnični podatki se ne mešajo.** Demo razpisi, partnerji in profili so vedno vidno označeni.
- **Migracije ne smejo brisati uporabniških podatkov.** Profil, reference, partnerji, načrti in ESPD osnutki ostanejo.
- **Skrivnosti ne gredo v Git.** `.env` je izključen. Ključev ne izpisuj v commite, dokumentacijo ali odgovore.
- Nove odvisnosti dodajaj le, kadar so res potrebne, in jih omeni v telesu commita (Migrations/config).

## Odprte točke in znane omejitve

Urejaj, ne dopisuj: ob rešitvi točko izbriši. Zgodovina je v `git log`.

- **Sinhrona AI analiza dokumentov.** `analyze_view` analizira dokumente zaporedno v HTTP zahtevi (časovna omejitev AI klica 45 s, gunicorn 120 s). Pri dolgih razpisih bo potrebna vrsta opravil v bazi in ločen worker (`manage.py analysis_worker`).
- **ESPD XML.** Izvoz v ESPD-EDM XML za uvoz v ESPD storitev e-JN ni narejen; zdaj sta na voljo tisk (PDF) in JSON.
- **Nepreverjen videz v brskalniku.** Zavihek ESPD, tisk ESPD in uvoz s spletne strani po prenovi dizajna (paleta v `workspace-theme.css`) še niso pregledani v brskalniku.
- **Kontrast ikone.** `.unmet > svg` (`#d45060`) ima na kremni podlagi kontrast 3,9:1; vse ostalo besedilo ima vsaj 4,5:1.
- **Omejen AI pomočnik.** Odgovor brez citata se zavrne, sporočila s »poišči«, »filter« ali omembo profila pa obdela pravilo brez AI. Splošnih vprašanj zato ne podpira. Možna razširitev: splošni odgovori z jasno oznako »ni preverjeno v dokumentaciji«.
- **Primerjava ujemanja ni izvedena.** `relevance_eval` in nabor `backend/eval/relevance_labels.csv` sta pripravljena, oznake pa še niso vpisane. Klic Gemini Decisions API je narejen po tipih iz SDK `google-genai` 3.2.0 (`POST /v1beta/decisions`) in še ni preizkušen z resničnim ključem. Nabor ima 21 razpisov in je neuravnotežen (prevladujejo gradnje). Odločitev o AI ujemanju v aplikaciji počaka na rezultate.
