# Obvestila o oddaji (pretekle oddaje)

- `raw/pjn_oddaje_2026-08-31_2026-11-11.json.gz`: izvorni izvoz Apify strgalnika `publicmoney/enarocanje-slovenia-scraper`
  (`phase: RESULT`, `fetchDetails: true`, zajem 11. 11. 2026). 2.300 obvestil o oddaji, objavljenih 31. 8.–11. 11. 2026.
  Zajem je bil omejen na 2.300 zapisov, zato obdobje od 11. do 30. 8. 2026 manjka.
- `past_awards.json.gz`: normalizirana tabela `PastAward` (7.257 sklopov), ki se samodejno naloži v prazno bazo.
  Ustvari jo `manage.py import_past_awards <izvoz.json[.gz]> --write-bundle`; zapis je ponovljiv (urejen, brez časovnega žiga).

Vir: Ministrstvo za javno upravo, Portal javnih naročil (https://www.enarocanje.si), licenca CC BY 4.0
(https://podatki.gov.si/dataset/api-pjn). Podatki so javne objave; neuspešni ponudniki v njih niso navedeni.
