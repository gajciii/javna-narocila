# Contracts on the website

The main navigation links to `#/pogodbe`. This shows the collected signed contracts, their
contractors, signed values, CPV, effective end dates, addenda counts and official PDF links.
The adjacent `#/pricakovani` tab retains the profile-based forecast of expiring contracts.
Both routes are allowed by the application route guard.

`GET /api/contracts` reads the existing database only. It does not collect new contracts,
call AI, create embeddings, or modify the selected company profile. Existing application
authentication applies. Results contain 20 signed contracts per page; addenda are represented
through the contract's extension date and count rather than duplicated as separate contracts.

Supported parameters:

- `q`: up to 200 characters / 8 words; words combine with AND across subject, buyer,
  contractor, buyer registration number and notice number.
- `cpv`: a 2–8 digit prefix.
- `year`: publication year.
- `status`: `all`, `active`, `ended`, `unknown`, or `expiring` (365 days).
- `sort`: `newest`, `ending`, or `value`; missing dates/values appear last.
- `page`: positive page number.

The dataset totals describe the entire collected register, while the result count describes
the current filters. Effective end dates include known addenda. Missing end dates remain
unknown; a signed value does not represent actual payments or an inferred sum of all addenda.
Expiry does not establish that a new tender will be published.

Validation covers filtering, JSON party searches, zero/unknown values, pagination, effective
end dates, validation errors and the absence of portal/AI calls on SQLite and PostgreSQL.
`npm run build --prefix frontend` checks and builds the frontend.

The production publication is staged and backed up under `/root/contracts-page-release`
on server-1. Source changes must also be included in subsequent image deployments.
