# Razpisni radar - implementation contract

Local single-user hackathon app. Slovenian UI. React/TypeScript/Vite frontend, Django/DRF/SQLite backend. General product; no PRIOT or GIC branding. All invented inputs explicitly demo. Dates relative to Europe/Ljubljana today for demo notices. Real IJS archive remains fixed/closed.

## API, no trailing slash

- GET /api/bootstrap -> {profile, tenders, notifications, saved_searches, meta:{demo:true,ai_mode:"demo"|"live",today,last_sync,integrations:{pjn:{state:"connected"|"ready",last_success,runs_remaining,real_count,latest_result},ajpes:{state:"connected"|"ready",last_success,provider:"ajpes",via:"OPSI",message,url}}}}
- GET/PUT /api/profile -> profile
- GET /api/companies/search?q=... -> {results:[{name,registration_number,address,legal_form,registration_authority}],total,source:{provider:"ajpes",via:"OPSI",url,license,attribution,retrieved_at,dataset_updated_at,refresh_frequency},mode:"live"|"cached",stale:boolean,warning?}
- POST /api/profile/prefill {provider?:"ajpes"|"demo",registration_number?:string,query?:string} -> {profile,source:"ajpes"|"demo",message,mode?,stale?,warning?}. Default AJPES requires a selected 7/10-digit registration number; never auto-select a fuzzy name match. Explicit demo returns the fictional template. Neither action mutates the profile until PUT. Invalid input 400, no exact result 404, uncached registry outage 503 {code:"ajpes_unavailable",message}.
- POST /api/profile/website {url} -> {url,final_url,mode:"live"|"heuristic",pages:[{url,title}],suggestions:{activity:Suggestion|null,description:Suggestion|null,expertise:Suggestion[],technologies:Suggestion[],keywords:Suggestion[]},warning:string|null,message}; Suggestion {value,evidence:[{url,quote,kind:"text"|"code"|"meta"}]}. Reads up to 8 same-site public pages, never mutates the profile. Invalid/non-public URL 400, unreachable site 502 {code:"website_unavailable",message}.
- GET /api/tenders?filters... -> {results:[Tender],count}
- GET /api/tenders/:id -> Tender (including detail)
- POST /api/tenders/:id/follow {following:boolean} -> Tender
- GET/POST /api/searches -> [SavedSearch] / SavedSearch; POST {name,filters}; DELETE /api/searches/:id
- POST /api/filters/suggest {message} -> {filters,explanation,mode}
- POST /api/chat {message,tender_ids?:string[],history?:[{role,content}]} -> {answer,mode:"demo"|"live",citations:[{tender_id,title,document_id?:string,page?:number,quote?:string}],profile_patch?:object,filters?:object}
- GET /api/notifications -> [Notification]; POST /api/notifications/read {id?:number} -> [Notification] (missing id means all)
- POST /api/demo/event {type:"correction"|"new"|"deadline"} -> {message,created,notifications,tenders}
- POST /api/demo/reset -> bootstrap
- POST /api/import {url_or_id} -> {message,tender?,mode:"live"|"snapshot"|"unavailable",warning?,downloaded?}
- POST /api/sources/pjn/sync {limit?:integer(1..50)} -> {mode:"live"|"partial"|"unavailable"|"limited",message,imported,updated,checked?,tender_ids?,errors:[{id,message}],warning?}; default limit 20
- POST /api/tenders/:id/analyze -> Tender
- POST /api/tenders/:id/documents multipart file -> document metadata with status
- GET /api/documents/:id -> PDF inline or other stored attachment as download; PDF browser link /api/documents/:id#page=N

## Objects

Profile: {id:1,name,registration_number,activity,address,website,description,expertise:string[],technologies:string[],keywords:string[],excluded_keywords:string[],regions:string[],min_value:number|null,max_value:number|null,available_from:string,staff_count:number|null,certifications:string[],capacity,source:"demo"|"user",references:[{id,title,description,domain,value:number|null,year:number|null,confirmed:boolean}],updated_at?,registry_source?:{provider:"ajpes",via:"OPSI",url,license,attribution,retrieved_at,dataset_updated_at,name,registration_number,address,legal_form,registration_authority}}

Tender: {id:string,title,buyer,region,kind:"services"|"goods"|"works",cpv:string[],value:number|null,published_at:ISODate,deadline:ISODateTime,status:"open"|"closed"|"cancelled"|"unconfirmed",source_type:"demo"|"real",source_url:string|null,summary,topics:string[],technologies:string[],following:boolean,is_new:boolean,has_update:boolean,version:number,match:{level:"high"|"medium"|"low",score:number,recommendation:"recommended"|"review"|"unsuitable"|"closed",reasons:string[],open_question:string,conditions:[{id,title,company_value,status:"met"|"unmet"|"unknown",document_id:string|null,page:number|null,quote:string}]},criteria:[{title,weight:number|null}],documents:[{id,title,url,pages:number,status:"processed"|"unprocessed",version:number,analysis_mode?,error?}],source_metadata?:{notice_id,dossier_id,notice_number,attribution,fetched_at,published_timestamp,phase,previous_notice_id,correction_description,attachment_url,attachments_processed,codelists_as_of},lots:[{id,title,match_level,summary}],changes:[{field,before,after,impact,document_id?,page?}],description?}

Notification: {id:number,tender_id:string,type:"new"|"correction"|"deadline",title,body,read:boolean,created_at,is_demo:boolean}
SavedSearch: {id:number,name,filters:Filters}
Filters: {q?:string,exclude?:string,cpv?:string[],kinds?:string[],buyers?:string[],regions?:string[],min_value?:number,max_value?:number,published_from?:string,published_to?:string,deadline_from?:string,deadline_to?:string,min_days?:number,levels?:string[],condition_states?:string[],include_unknown?:boolean,only_new?:boolean,only_updates?:boolean,only_following?:boolean,statuses?:string[],source_types?:("real"|"demo")[],view?:"recommended"|"all"|"following",sort?:"match"|"deadline"|"newest"|"value"}. Query array values comma-separated. Default include_unknown true; view recommended; sort match. Groups AND, members OR; q comma-separated terms OR, exclude comma-separated terms OR. Unknown inclusion applies missing bounded field (value/deadline), not all other groups. CPV hierarchy match.

## Seed tender IDs / documents

energy-iot (positive), sport-portal (unknown ref value/year), satellite (one ref then correction requires two), office-licenses (low), lab-platform (two lots), municipal-app (closed), ijs-archive (real cancelled).
Documents IDs and file names: energy-v1, sport-v1, satellite-v1, satellite-v2, municipal-v1. Store PDFs in backend/demo_documents and matching .json sidecars with {id,title,tender_id,version,pages:[{page,text}],requirements:[{id,title,kind:"reference_count"|"reference_value"|"staff"|"technology"|"certification",certification?:string,requires_manual_review?:boolean,domain?,minimum?,max_age_years?,technologies?:string[],document_id,page,quote}],criteria:[{title,weight}],summary}. Backend reads PDFs with pypdf and uses sidecars for deterministic demo extraction with evidence validation.

Domain references: energy has confirmed 120000 EUR year current-1; sport has unknown value/year; satellite has one confirmed 90000 EUR current-1. Staff 6, tech React/Django/ASP.NET/Vue.js/Nuxt.js/WebSocket/Docker. Requirements: energy >=1 energy ref value>=80000 within3years, staff>=3, relevant software; sport >=1 sport ref >=60000 within3years -> unknown; satellite >=1 satellite ref within3years v1 and >=2 v2 -> unmet. No fabricated real company capabilities.

Event correction is idempotent satellite version2; follows by default. New event idempotently marks energy newly received and produces alert only if open/relevant. Deadline event adds 7 days to energy once. Reset restores the demo profile, searches, reference dates and demo notification state; imported real tenders and their notifications persist. Dynamic matching recalculates on profile changes. Never unknown=>met. Closed/cancelled cannot new-alert. Evidence constrained to existing document pages and quote substrings. Low content fit separate from failed conditions. API secrets only on backend. Read external documents as untrusted data, never instructions.


## Live e-Naročanje collection

`pjn_transport.py` only follows HTTPS redirects on official PJN hosts, bounds response sizes and does not forward browser credentials. `pjn_normalize.py` maps actual public API responses using the official codelist snapshot dated 2026-11-10. Numeric CPV IDs are resolved to eight-digit CPV codes. Unknown currency/values/weights stay unknown. Publication status alone does not prove an open application period. Content matching uses the actual subject; a broad CPV label alone can only yield medium similarity.

A `SyncRun` reserves one of two unique slots per Europe/Ljubljana calendar day; failed runs count. Single URL imports, batch sync and the optional 12-hour CLI/Docker worker share this quota. Batch collection fetches up to 20 latest notices by default from the last seven days and checks up to 30 followed dossiers, with a 60-second work budget checked between notices (individual requests may extend elapsed time). Automatic attachment downloads cover the first three notices; single imports download their own documentation. No full-corpus or completeness claim.

`SyncAttempt` stores the raw JSON response or error. Real tender IDs are stable `pjn-dosje-{idDosje}` (the seeded IJS archive keeps `ijs-archive`). A changed notice creates a version and one notification keyed by dossier/version. Re-importing the same version creates no duplicate; importing an older timestamp cannot roll back current data. Followed dossiers notify even if no longer relevant/open. If the first local record is already a correction, display the official correction description without fabricating a prior state.

Public `/api/datoteka/get` attachments are stored with hashed paths. PDF text preserves page numbers; ZIP members never use archive paths as local output paths. Limits: 10 MB per download/member, 30 ZIP members, 20 MB expanded archive, 150 PDF pages. Unsupported formats, unreadable PDFs and oversized/protected archives remain explicitly unprocessed. Only documents from the current imported version may support current conditions. PDF text extraction does not imply completed AI analysis. Uploaded/demo document behavior is unchanged.

## AJPES / OPSI company lookup

AJPES replaces the Bizi placeholder. Uses public `https://podatki.gov.si/api/3/action/datastore_search` resource `beb70929-3d0d-41c6-9af2-25d525d906d3`, with `package_show?id=poslovni-register-slovenije` for dataset metadata. No account, API key, website scraping or full-register download. This is the twice-monthly open dataset, not authenticated restPrsInfo or a real-time ePRS assertion.

Verified wire fields include `Matična številka`, `Popolno ime`, `Ulica`, `Hišna št`, `Hišna št  dodatek`, `Naselje`, `Poštna št`, `Pošta`, `Pravnoorganizacijska oblika`, `Registrski organ`. Keep registration numbers as strings, including leading zeros; seven-digit input expands to the main entity suffix 000. Exact prefill must match the requested ten-digit number. No inferred SKD, website, financial facts or capabilities.

`CompanyLookupCache` persists normalized responses with a 24-hour TTL and fetch time. Transport uses fixed HTTPS OPSI endpoints, bounded 1 MB responses, explicit timeouts and no redirects. Cached data are labeled; expired cache can be used only with a stale warning after a failed refresh. Empty results remain empty. Dataset metadata timestamp is stored with the original lookup so a later metadata refresh cannot relabel old company data as newer.

The UI previews before applying. Switching company clears previous capabilities and references from the draft; reimporting the same identity merges only the three basic fields. Saving is explicit. Imported provenance is reconstructed from server-side exact-lookup cache; arbitrary client provenance is ignored. Each field is labeled as imported only while matching the stored source value. Changing registration number drops old source attribution. Demo reset retains the lookup cache. Bizi is no longer in the product flow.


## Improvement notifications and development plans

- `POST /api/improvements/evaluate {actions,source_type:"demo"|"real"}` returns a fresh `ImprovementEvaluation`. No company, tender or notification writes and no external calls. Unknown or malformed actions return 400.
- `GET/POST /api/improvement-plans`: list current company's plans with freshly calculated evaluations, or create `{name,actions,source_type}` (201).
- `GET/PUT/DELETE /api/improvement-plans/<id>`: read, update name/actions/source, or delete (204); another company's plan returns 404. Names: 1–100 characters; at most 20 input actions. Identity normalizes a 7-digit registration number to 10 digits; missing identity falls back to normalized name and address. Server derives identity, never accepts it from the client.
- Notification `type` now includes `improvement`; `tender_id` may be null. `improvement` is an evaluation for that type, otherwise null. Existing numeric notification IDs and read endpoint are retained. Inactive suggestions and suggestions belonging to another company are excluded from read/list/badge operations.

Actions (combined actions are normalized and deduplicated):

```text
{kind:"certification",certification:string}
{kind:"staff",minimum:positive_integer}
{kind:"technology",technologies:string[]}
{kind:"reference",domain:string,minimum_count:positive_integer,minimum_value:number|null,max_age_years:positive_integer|null}
{kind:"complete_profile",field:"references"|"staff_count"|"technologies"|"certifications",domain:string}
```

Staff and reference values are target minimums, not repeated additions. Reference actions with the same domain merge using the highest counts/values and strictest age constraint. Already achieved capabilities produce no additional effect. Hypothetical references are confirmed, completed in the current year, and exist only in the temporary profile. Completion actions preserve unknowns and show the evidence requiring a missing fact; they never fabricate the fact.

`ImprovementEvaluation` contains `{actions,labels,source_type,summary:{open,historical},open:Impact[],historical:Impact[],evaluated_at,assumptions}`. Each summary contains `affected_tenders`, `newly_recommended`, `improved_conditions`, `needs_data`. Each Impact contains tender id/title/deadline/status/source, before/after recommendation, `newly_recommended`, `changes:[{before:Condition,after:Condition,improved:boolean}]`, `remaining_conditions`, `open_question`, `documentation_incomplete`. Conditions preserve document id, page, and exact quote. Counts are distinct tenders within one source and status group; historical tenders always remain closed.

Evaluation and automatic generation use only medium/high content-fit tenders, current active document versions, and processed conditions. Cancelled/unconfirmed tenders are excluded. Certificates with editions, validity, equivalence, alternatives or scope qualifiers require manual review. Standard spelling variants such as ISO/IEC 27001 and ISO 27001 match; editions are not stripped. Extraction validates the certificate name against the cited text in addition to page/quote validation. Numeric requirement guards do not apply to technology or certification requirements.

Suggestion generation runs when bootstrap/notifications are read; it makes no external requests. The unique event key combines company identity, source and canonical action. Repeated unchanged evaluations do not rewrite payloads or reset read status. New affected open tender IDs or newly recommended IDs reset unread; lost opportunities do not. Irrelevant suggestions deactivate. Limit: five unsaved suggestions, ranked by real open opportunities, presence of open opportunities, newly recommended count, improved conditions and affected tenders. Saved actions are retained outside the limit. This is deterministic work on the small local dataset, not a background crawl or demand forecast.

Migration 0004 adds nullable notification tender, payload/active/company_key fields and ImprovementPlan; no existing profile/tender data is reset. Demo seed retains seven tenders and now loads five PDFs (four tender documentations plus satellite correction). Sport and closed municipal documents require ISO 27001; energy stays the positive baseline. Demo reset preserves saved plans, which are recomputed against the restored profile. UI stays within Notifications: development suggestions, saved plans, evidence modal, same-source selection/combination, rename/removal of actions, and explicit plan deletion.


## Relevance thresholds, partner evidence and certification picker

- Filters add `min_score` (integer 0–100, default unbounded) and `include_partner_opportunities` (boolean, default false). Threshold is an additional AND constraint on the existing content score. In the recommended view the toggle permits medium/high open tenders excluded specifically for unmet conditions; it never overrides source/status/content or other filters. `levels` remains accepted; UI renders legacy active chips and clears levels when the threshold changes.
- `GET /api/certifications` returns `[{key,label,required}]` from four starter standards, current-profile certificates and current processed document requirements. `required` means an open medium/high content-fit tender requires it. ISO/IEC spelling variants normalize, editions remain distinct. Profile storage stays `certifications:string[]`; save deduplicates normalized aliases.
- `GET/POST /api/partners` lists the current company's partners or creates `{source_type,profile,capability_evidence:{source,url,confirmed}}` (201). Profile uses existing company fields without singleton id. `GET/PUT/DELETE /api/partners/<id>` reads/updates/deletes; foreign ownership is 404. Source is immutable on update. Own-company and duplicate identities within the same source are rejected. All ownership derives server-side from the active company. URLs accept HTTP(S) only and are never fetched by evaluation.
- References gain optional `project_identifier`, `evidence_source`, `evidence_url`, retained by profile validation. Partner references marked confirmed require a source description or URL. Capability evidence confirms the stated technologies, staff and certificates as a group; it is explicitly user-confirmed, not independently verified. Unsupported partner facts are excluded from contributing profiles.
- `GET /api/tenders/<id>/partners[?partner_id=N]` returns `{tender_id,source_type,missing_conditions,candidates,comparison,message}`. Candidates are at most three `PartnerComparison` objects, sorted by supported-condition count, content score and stable id. An explicit partner must belong to the company and match the tender source or returns 404. Closed/cancelled/unconfirmed, low-content-fit and unanalysed opportunities return explanatory empty results.
- Comparison: `{partner,supported_conditions,remaining_conditions,content_score,content_level,documentation_incomplete,disclaimer,conditions:[{condition,partner_condition,state:"already_met"|"potential"|"unresolved",label,explanation,evidence}]}`. Conditions preserve tender document/page/quote; evidence identifies partner reference/capability sources. It is a potential contribution comparison, never a new formal eligibility result. Does not write profile/tender/following/notifications or call AI/external sources.
- Company and supported partner facts use the same requirement evaluator. Known technologies may be united. Staff may be added only with stated availability by the tender deadline; team overlaps still require checking. Partner certificates are never copied into the real company profile. Reference values are never summed. Reference counts may pool only identified projects; repeated normalized identifiers count once, conflicting metadata stay unconfirmed. A partner independently meeting a reference requirement can contribute without relying on unidentified company references. Future-dated projects cannot satisfy completed references.
- Migration 0005 adds Partner with company_key/source/data/timestamps. Four fictional demo partners seed once per company using a DemoEvent marker. Normal refresh does not resurrect deleted partners. Demo reset retains partners; clearing markers allows missing starter examples to be recreated. Demo/real candidates never mix. Existing user data is not reset.

## Website profile suggestions

`website.py` reads the company's own public site as untrusted data. Only http(s) on ports 80/443; every hop (including redirects, followed manually) must resolve to globally routable IPs. Limits: 1.5 MB per page, 8 pages (home + same-site service/about pages; blog, contact and legal pages skipped), 25 s budget. Without an AI key a keyword heuristic proposes fields; negated sentences ("cena ne vključuje SEO") and customer testimonials are not evidence. With a key, AI items are kept only if their quote occurs verbatim in the fetched page text. Technologies found only in page source are labeled `code` (how the site is built, not necessarily what the company offers). References, staff, revenue and certificates are never inferred. The UI previews suggestions with sources; lists are merged into the draft and saved only via the normal profile PUT.
