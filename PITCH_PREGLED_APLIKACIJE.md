# Razpisni radar — kaj ponuja aplikacija

Ta dokument opisuje trenutno izvedeni prototip in služi kot podlaga za pitch. Loči med delujočimi funkcionalnostmi, povezavami z zunanjimi viri in demonstracijskimi podatki.

## 1. Ideja v enem stavku

**Razpisni radar poveže javne razpise s sposobnostmi podjetja, pojasni primernost in pokaže, kaj podjetju še manjka za naslednji korak.**

Podjetju pomaga odgovoriti na pet vprašanj:

1. Kateri razpisi so za nas vsebinsko zanimivi?
2. Katere obdelane pogoje izpolnjujemo in kateri podatki še manjkajo?
3. Kaj se je spremenilo in kako to vpliva na našo odločitev?
4. Ali bi nam pri manjkajočem pogoju lahko pomagal partner?
5. Katere izboljšave podjetja bi odprle dodatne možnosti?

## 2. Problem, ki ga rešujemo

Objava zanimivega razpisa še ne pove, ali je prijava za podjetje smiselna. Ekipa mora pregledati predmet naročila, roke, priloge, reference, kadrovske zahteve in certifikate ter vse primerjati s svojimi sposobnostmi. Ob popravkih mora del pregleda ponoviti.

Razpisni radar te informacije poveže v en uporabniški tok: **najdi priložnost → razumi zahteve → preveri vrzeli → odloči se za naslednji korak**.

Cilj je skrajšati predhodni pregled in zmanjšati možnost, da podjetje spregleda pomemben pogoj ali spremembo. Prihranek časa v trenutnem prototipu še ni izmerjen.

## 3. Komu je namenjen

- Podjetjem, ki želijo spremljati javna naročila glede na svoje dejanske sposobnosti.
- Poslovnim in prodajnim ekipam, ki izbirajo priložnosti za prijavo.
- Strokovnim sodelavcem, ki preverjajo reference, kadre in tehnične zahteve.
- Vodstvu, ki želi razumeti, katere kompetence bi bilo smiselno razvijati.

Rešitev je splošna. Demonstracija uporablja izmišljeno tehnološko podjetje, funkcionalnosti pa niso vezane na določeno podjetje. Trenutni algoritem je prototip z omejenim naborom prepoznanih področij; enake kakovosti za vse panoge še nismo preverili.

## 4. Kaj uporabnik dejansko dobi

### 4.1 Profil podjetja, na katerem temeljijo priporočila

Podjetje poišče svoj naziv ali matično številko. Aplikacija prek javnega nabora AJPES na OPSI pridobi **naziv, matično številko in naslov**. Uporabnik podatke pregleda in potrdi.

Profil dopolni z:

- dejavnostjo, opisom ponudbe, strokovnimi področji in ključnimi besedami;
- tehnologijami in kompetencami;
- referencami: področje, opis del, vrednost, leto, potrditev ter po potrebi identifikator projekta in dokazilo;
- številom razpoložljivih sodelavcev, razpoložljivostjo in zmogljivostmi;
- certifikati;
- želenimi lokacijami, obsegom projektov in izključenimi izrazi.

**Vrednost:** priporočila upoštevajo podatke konkretnega podjetja. Dopolnitev profila spremeni oceno pogojev in priporočila.

Pri osnovnih podatkih je viden izvor. AJPES v tej povezavi ne zagotavlja referenc, certifikatov, kadrov, prihodkov ali dejavnosti SKD; te podatke uporabnik vnese posebej. Podatki AJPES prihajajo iz periodično posodobljenega odprtega nabora.

### 4.2 Razpisi z naprednim filtriranjem

Začetna stran vsebuje poglede **Priporočeno zame**, **Vsi razpisi** in **Spremljam**. Uporabnik lahko razpise razvršča, spremlja in shranjuje iskanja.

Filtriranje podpira:

- ključne besede in izključene izraze;
- kategorije CPV ter storitve, blago ali gradnje;
- naročnika, lokacijo in vrednost;
- datum objave, rok prijave in najmanjše število dni do roka;
- stanje obdelanih pogojev;
- nove objave, popravke in spremljane razpise;
- stanje razpisa ter ločevanje resničnih in demo podatkov;
- vključevanje neznanih vrednosti pri filtriranju vrednosti in roka.

Različne skupine filtrov se kombinirajo z **IN**, več izbir znotraj iste skupine pa z **ALI**. Iskanje je mogoče shraniti in ponovno odpreti.

**Najmanjše vsebinsko ujemanje** uporabnik nastavi z drsnikom ali številčnim vnosom od 0 do 100. Kartice in podrobnosti pokažejo rezultat, na primer **Ujemanje: 82/100**. Ocena izraža podobnost dejavnosti podjetja in predmeta naročila; izpolnjevanje pogojev se preverja posebej.

Stikalo **Vključi priložnosti s partnerjem** v priporočenem pogledu razkrije tudi odprte, vsebinsko ustrezne razpise z neizpolnjenimi pogoji. Prag in stikalo se shranita z iskanjem.

Uporabnik lahko iskanje tudi opiše z besedami. Aplikacija iz prepoznanih izrazov pripravi predlog vidnih filtrov, ki ga uporabnik potrdi. Ta funkcija trenutno uporablja pravila za prepoznavanje izrazov.

**Vrednost:** podjetje določi, kakšne priložnosti želi pregledovati, in hitro ponovi isti izbor.

### 4.3 Razložljiva presoja razpisa z dokazi

Podrobnosti razpisa združujejo povzetek, naročnika, datume, vrednost, sklope, dokumente, izvorno povezavo, pogoje in merila ocenjevanja.

Pri vsakem obdelanem pogoju so prikazani:

- zahteva naročnika;
- ustrezni podatek podjetja;
- rezultat **Izpolnjen**, **Ni izpolnjen** ali **Neznan**;
- citat iz dokumentacije ter povezava na dokument in stran.

Podprte vrste preverjanja so število primerljivih referenc, vrednost posamezne reference, starost reference, velikost ekipe, tehnologije in certifikati. Nepodprte ali neobdelane zahteve potrebujejo dodaten pregled.

Pogoji sodelovanja so prikazani ločeno od meril ocenjevanja. Manjkajoča vrednost reference ali neanalizirana dokumentacija ostane označena kot neznana oziroma nepreverjena. Posebna različica, veljavnost ali obseg certifikata prav tako zahtevajo preverjanje.

**Vrednost:** uporabnik vidi razloge za oceno in lahko preveri podlago neposredno v dokumentu.

### 4.4 AI pomočnik za predhodno pripravo na prijavo

Pomočnik uporablja profil podjetja, ocene razpisov in razpoložljive odlomke dokumentacije. Vmesnik uporabnika vodi skozi tri glavne naloge:

1. **Poišči primerne razpise.**
2. **Preveri pogoje za prijavo.**
3. **Primerjaj dva razpisa.**

Uporabnik lahko vpraša tudi, zakaj je razpis priporočen, katere reference manjkajo ali kaj mora še preveriti. Odgovori imajo povezave do razpisov in razpoložljivih dokazov. Pomočnik lahko predlaga dopolnitev področij profila ali filtre; uporabnik predlog izrecno potrdi.

**Vrednost:** podjetje lažje razume zahteve in odprta vprašanja pred odločitvijo za pripravo ponudbe.

Integracija z jezikovnim modelom je implementirana in zahteva strežniški OpenAI API ključ. Brez ključa deluje označen demo način z odgovori iz shranjenih podatkov in pravil. Živi klici modela pri dosedanjem preverjanju niso bili preizkušeni. Priprava celotne ponudbe, izpolnjevanje obrazcev in oddaja prijave še niso izvedeni.

### 4.5 Obvestila o novih priložnostih in spremembah

Obvestila znotraj aplikacije pokrivajo novo relevantno objavo, spremembo spremljanega razpisa, popravek pogojev in spremembo roka. Podrobnosti omogočajo pregled spremembe **prej → zdaj**, kadar sta obe različici shranjeni.

Spremljani razpis lahko sproži obvestilo o spremembi tudi, ko po spremembi ni več primeren. Ponovljen uvoz iste različice ne ustvarja dvojnikov. Kadar stare različice ni, se prikaže razpoložljivi izvorni opis spremembe.

**Vrednost:** podjetje hitreje opazi spremembo, ki lahko vpliva na prijavo.

Obvestila se v odprti aplikaciji preverjajo vsakih 30 sekund. Novosti iz e-Naročanja postanejo znane ob naslednjem zajemu; običajni lokalni zagon zajema ne sproža samodejno. E-poštna in potisna obvestila še niso vključena.

### 4.6 Samodejni predlogi za razvoj podjetja

V **Obvestila → Predlogi za razvoj** aplikacija iz obdelanih pogojev odkrije, katere spremembe bi podjetju pomagale:

- pridobitev oziroma evidentiranje zahtevanega certifikata;
- dodatna primerljiva referenca z zahtevano vrednostjo in starostjo;
- večja razpoložljiva ekipa;
- dodatne tehnologije;
- dopolnitev manjkajočih podatkov profila.

Gumb **Poglej učinek** primerja trenutno stanje z začasno spremenjenim profilom. Ločeno pokaže število razpisov z dodatno izpolnjenim pogojem, nova priporočila za pregled in preostale ovire. Odprti in pretekli razpisi ter demo in resnični podatki imajo ločena štetja.

Predloge lahko uporabnik poimenuje, shrani v **razvojni načrt**, združi več izboljšav istega vira ter načrt kasneje ponovno odpre in preračuna. Simulacija ne spremeni dejanskega profila. Števila izhajajo iz shranjenih pogojev in trenutnega profila; za ta izračun ni dodatnega AI klica.

**Vrednost:** podjetje poleg trenutnih priložnosti vidi tudi konkretne vrzeli, ki jih lahko obravnava v razvojnem načrtu. Zgodovinski pogled pokaže učinek na shranjene pretekle razpise; prihodnjih objav ne napoveduje.

### 4.7 Partnerji za skupno prijavo

Zavihek **Partnerji** v podrobnostih razpisa najprej pokaže odprte pogoje. Pri neznanih podatkih ponudi dopolnitev profila, pri podprtih kandidatih pa največ tri najuporabnejše partnerje.

Za vsakega partnerja so prikazani prispevek, povezana dokazila in preostala vprašanja. **Poglej skupni potencial** primerja podjetji po posameznih pogojih: vaše podjetje, partner in možen skupni prispevek.

Primerjava upošteva omejitve:

- tehnologije in znano razpoložljive kadre lahko primerja skupaj;
- vrednosti različnih referenc se ne seštevajo za zahtevo po eni dovolj veliki referenci;
- skupno število referenc zahteva prepoznavne različne projekte; isti projekt šteje enkrat;
- partnerjev certifikat je prikazan kot njegov prispevek;
- nepodprte navedbe in nepotrjena dokazila ne postanejo potrjena sposobnost;
- način skupne prijave je treba preveriti v dokumentaciji.

**Upravljaj partnerje** omogoča dodajanje, urejanje in brisanje. Osnovne podatke je mogoče predizpolniti z AJPES. Kompetence, ekipo, certifikate, reference in dokazila uporabnik vnese posebej. Potrditev dokazila je uporabniška, ne neodvisna verifikacija aplikacije.

**Vrednost:** podjetje vidi, pri katerih konkretnih pogojih bi lahko partner pomagal in kaj bi še ostalo odprto.

Trenutno gre za lasten seznam partnerjev in štiri izmišljene demo partnerje. Javni imenik, samodejno pridobivanje referenc in kontaktiranje podjetij niso izvedeni. Primerjamo enega partnerja naenkrat. Demo in resnični partnerji ostajajo ločeni.

### 4.8 Pregledna izbira certifikatov

Certifikati se izbirajo iz iskalnega spustnega seznama z večkratno izbiro. Začetne možnosti so **ISO 9001, ISO 14001, ISO/IEC 27001 in ISO 45001**; seznam dopolnjujejo certifikati iz profila in obdelanih pogojev razpisov.

Relevantne zahteve so označene z **Zahtevano v vaših razpisih**. Uporabnik lahko izbiro odstrani ali doda drug certifikat. Običajni zapisi istega standarda se ne podvajajo, različice standardov ostanejo ločene.

**Vrednost:** enotnejši podatki profila omogočajo bolj dosledno primerjavo s pogoji. Izbira predstavlja uporabniško navedbo certifikata.

## 5. Kaj je povezano z resničnimi viri

| Del | Trenutna izvedba | Pomembna meja |
|---|---|---|
| e-Naročanje | Delujoč uvoz po ID-ju ali povezavi, zajem novih objav, preverjanje različic spremljanih dosjejev in prenos dostopnih prilog. | Omejen zajem, največ dva zagona dnevno. Samodejni 12-urni proces je treba posebej vključiti. |
| AJPES prek OPSI | Delujoče iskanje in predizpolnitev naziva, matične številke in naslova brez API ključa. | Periodično osvežen javni nabor; ne vsebuje referenc in sposobnosti podjetja. Bizi ni uporabljen. |
| Dokumenti | Prenos dostopnih prilog, obdelava podprtih ZIP arhivov in izluščevanje besedila PDF-jev po straneh. | Skenirani, zaščiteni in nepodprti dokumenti ostanejo neobdelani. Zunanje povezave lahko zahtevajo ročni pregled. |
| AI analiza | Implementirana ekstrakcija podprtih pogojev in meril ter chat prek strežniškega API-ja. Sklici na dokaze se preverjajo. | Potreben je API ključ; prenos PDF-ja sam še ne pomeni analize pogojev. Živi AI klici še niso preverjeni. |
| Ujemanje, razvojni predlogi in partnerji | Delujoče primerjave nad trenutnim profilom in shranjenimi podatki. | Vsebinska ocena uporablja razložljiva pravila. Presoja pokriva obdelane, podprte pogoje. |

Živi zajem e-Naročanja in iskanje AJPES sta bila uspešno preverjena. Začetni klon vsebuje pripravljen demo in arhivski zapis; dodatne resnične objave pridobi z zajemom. Lokalno prenesene datoteke in baza se ne prenašajo prek Gita.

## 6. Kaj lahko pokažemo na demonstraciji

Začetni nabor vsebuje **sedem razpisov: šest izmišljenih in en resničen arhivski zapis**. Priložena je dokumentacija za štiri demo razpise in dodatna popravljena različica satelitskega razpisa. Arhivski zapis je ustavljen in se ne predstavlja kot aktualna priložnost.

| Primer | Kaj pokaže |
|---|---|
| IoT platforma za spremljanje porabe energije | Začetno dobro ujemanje in izpolnjene obdelane demo pogoje. |
| Portal za upravljanje športnih tekmovanj | Manjkajoče podatke reference, zahtevo ISO 27001 in različne prispevke partnerjev. |
| Analiza satelitskih posnetkov | Popravek z ene na dve referenci, obvestilo, spremembo priporočila in partnersko priložnost. |
| Podaljšanje pisarniških licenc | Razlikovanje med razvojem programske rešitve in dobavo licenc. |
| Digitalizacija laboratorija | Različno vsebinsko ujemanje razvojnega in dobavnega sklopa. |
| Zaključena mobilna aplikacija | Izločitev iz odprtih priložnosti in zgodovinski učinek certifikata. |
| Arhivska objava za spletno platformo IJS | Resnične izvorne podatke in pravilno obravnavo ustavljenega naročila. |

### Predlagan petminutni tok

1. **Profil:** pokažemo podatke podjetja in sposobnosti, na katerih temelji presoja.
2. **Izbor:** nastavimo najmanjše ujemanje in odpremo energetski razpis.
3. **Dokaz:** pokažemo en izpolnjen pogoj ter citat na konkretni strani PDF-ja.
4. **Vrzel:** pri športnem portalu pokažemo neznane podatke in partnerjev prispevek; preostali pogoj ostane viden.
5. **Sprememba:** sprožimo označen demo popravek satelitskega razpisa ter odpremo obvestilo. Vključimo priložnosti s partnerjem.
6. **Razvoj:** odpremo predlog za certifikat, pokažemo izračunan učinek in shranimo načrt.
7. **Pomočnik:** vprašamo, kaj je treba preveriti pred prijavo, in pokažemo povezavo do vira. Brez ključa povemo, da gre za demo odgovor.

Pred predstavitvijo ponastavimo demo stanje in preverimo tok. Prikazana štetja so odvisna od trenutnega profila in podatkov, zato jih preberemo iz aplikacije.

## 7. Glavne točke za pitch

- **Prilagojeno podjetju:** isti razpis se presoja glede na konkretne reference, kadre, tehnologije in certifikate.
- **Razlaga z dokazom:** uporabnik vidi, zakaj je pogoj izpolnjen, neizpolnjen ali neznan, ter odpre vir.
- **Naslednji korak:** pri vrzeli lahko dopolni profil, pregleda partnerja ali shrani razvojno izboljšavo.
- **Učinek sprememb:** popravek razpisa in dopolnitev profila vplivata na aktualno presojo.
- **Od trenutne priložnosti do razvoja:** isti podatki podpirajo izbor današnjih razpisov in razmislek o prihodnjih kompetencah.

To so poudarki naše izvedbe; primerjava s konkurenčnimi izdelki še ni bila opravljena.

## 8. Predlog kratkega pitcha

> Podjetje lahko najde zanimiv javni razpis, nato pa mora iz prilog ugotoviti, ali ima ustrezne reference, ekipo in certifikate. Razpisni radar poveže objave s profilom podjetja in pri obdelanih pogojih pokaže, kaj izpolnjuje, kaj manjka in kje je dokaz. Spremlja spremembe, primerja možen prispevek partnerja ter izračuna, katere izboljšave bi podjetju odprle dodatne možnosti. V prototipu delujeta povezavi z e-Naročanjem in javnimi podatki AJPES, celoten tok pa pokažemo na označenih demo primerih.

**Kratek poudarek za zaključek:** »Od objave razpisa do jasnega naslednjega koraka za vaše podjetje.«

## 9. Meje trenutne različice in tehnična podlaga

Trenutna različica je lokalni prototip z enim uporabnikom. Profili, iskanja, spremljanje, partnerji in načrti se shranjujejo. Partnerji in načrti so vezani na identiteto podjetja, produkcijska registracija in večuporabniška izolacija pa še nista izvedeni.

Naslednje faze lahko vključujejo produkcijsko prijavo, e-poštna obvestila, OCR in dodatne dokumentne formate, širši zajem, več podprtih pogojev ter pripravo dokumentov za ponudbo. Ocena stroškov izboljšav in napovedovanje prihodnjih razpisov še nista del aplikacije.

Tehnična podlaga: **React, TypeScript in Vite** za vmesnik, **Django in Django REST Framework** za strežnik, **SQLite** za shranjevanje, **pypdf** za PDF-je ter **OpenAI Responses API** za izbirno živo AI obdelavo. Pripravljen je Docker Compose. Pri zadnji implementaciji je bilo uspešnih **121 avtomatskih testov**, produkcijska gradnja ter namizni in mobilni pregled novega toka. Zagon vsebnikov in živi AI klici še niso bili preverjeni.

Podrobnosti zagona in integracij: [README.md](README.md). Tehnični vmesniki: [CONTRACT.md](CONTRACT.md).
