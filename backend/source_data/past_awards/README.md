# Obvestila o oddaji (pretekle oddaje)

- `raw/pjn_oddaje_2026-08-31_2026-11-11.json.gz`: izvorni izvoz Apify strgalnika `publicmoney/enarocanje-slovenia-scraper`
  (`phase: RESULT`, `fetchDetails: true`, zajem 11. 11. 2026). 2.300 obvestil o oddaji, objavljenih 31. 8.–11. 11. 2026.
  Zajem je bil omejen na 2.300 zapisov; starejše obdobje dopolnjuje spodnji izvoz.
- `raw/pjn_oddaje_2026-06-25_2026-08-28.json.gz`: združen izvoz istega strgalnika
  (`phase: RESULT`, `fetchDetails: true`, `schemaOrg: false`, zajem 12. 11. 2026).
  2.085 različnih obvestil, objavljenih 25. 6.–28. 8. 2026, oziroma 4.776 dodatnih sklopov.
  Podvojitve so odstranjene po ID-ju obvestila. Zajem je bil omejen s proračunom; najstarejši dan je lahko nepopoln.
  Dva zagona sta skupaj stala 4,79625 USD od dovoljenih 5 USD. Prvi je bil ustavljen, ker je po selitvi
  na drug strežnik začel ponavljati zapise; drugi je nadaljeval pri najstarejšem doseženem dnevu.
  Parametri zagonov, stroški in števila zapisov so v pripadajoči datoteki `.provenance.json`.
- `past_awards.json.gz`: normalizirana tabela `PastAward` (12.033 sklopov iz 4.385 obvestil,
  objavljenih 25. 6.–11. 11. 2026), ki se samodejno naloži v prazno bazo.
  Ustvari jo `manage.py import_past_awards <izvoz.json[.gz]> --write-bundle`; zapis je ponovljiv (urejen, brez časovnega žiga).

Vir: Ministrstvo za javno upravo, Portal javnih naročil (https://www.enarocanje.si), licenca CC BY 4.0
(https://podatki.gov.si/dataset/api-pjn). Podatki so javne objave; neuspešni ponudniki v njih niso navedeni.
